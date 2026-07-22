---
sidebar_position: 6
---

# Host Policy Deployment on Unitree G1

This workflow runs a LeRobot policy service on a host workstation and the
Teleopit motion tracker on the G1 onboard computer. The two repositories use
separate Python environments and communicate only through strict
ZeroMQ/msgpack messages.

```text
Host workstation (lerobot-teleopit)
  ReplayPolicy or ACT -> policy server
                              |
                              | float32 state/action + JPEG over TCP
                              v
G1 onboard computer (Teleopit)
  RealSense + G1 state -> client -> validated 30 Hz action chunk
  -> 50 Hz interpolation -> motion tracker -> G1 joint-angle targets
                           -> LinkerHand O6 / OpenNeck
```

This is a separate runtime from Pico teleoperation. Do not start PicoBridge,
GMR, or `run_sim2real.py` for this workflow. Switching between Pico control and
host-policy control means stopping one runtime and starting the other.

## 1. Network Messages and Hand Calibration

The current client/server code and protocol tests define the request and
response structure. During active development, changes to that structure must
be made in Teleopit and `lerobot-teleopit` together; old network envelopes are
not supported.

The only shared data file is carried in both repositories:

```text
lerobot-teleopit/src/lerobot_teleopit/hand_calibration.json
Teleopit/teleopit/high_level_policy/hand_calibration.json
```

`hand_calibration.json` defines the LinkerHand O6 raw open/close values and
range tolerance. The current `describe` response identifies the 68D
observation as `teleopit-g1-state` and the canonical 50D action as
`teleopit-g1-reference`. The action layout and physical-degree OpenNeck
commands are enforced by the current code and tests.

The canonical action layout is:

```text
[0:3]    session-local root x/y and absolute z
[3:7]    session-local root quaternion, wxyz
[7:36]   G1 29D reference joint positions, radians
[36:48]  left/right LinkerHand O6 closure, [0, 1]
[48:50]  OpenNeck yaw/pitch, physical degrees
```

The host sends reference motion, never G1 motor commands. Teleopit routes the
body slice through the existing motion tracker, which produces joint-angle
targets for the local G1 controller.

## 2. Prepare the Host

Use the independent `lerobot-teleopit` environment on the workstation. For a
first network test, start ReplayPolicy before using ACT:

```bash
cd /path/to/lerobot-teleopit
uv run teleopit-policy-server \
  --dataset-root data/lerobot/teleopit_v3 \
  --repo-id local/teleopit_v3 \
  --episode 0 \
  --chunk-size 15 \
  --bind tcp://0.0.0.0:5555
```

For ACT, use the host repository's checkpoint command instead. Allow TCP port
`5555` only on the trusted robot network. The protocol deliberately has no
remote shutdown or motor-control endpoint.

## 3. Prepare the Onboard Runtime

Install Teleopit and the hardware dependencies in its own environment:

```bash
pip install -e '.[openneck]'
git submodule update --init --recursive
pip install -e third_party/linkerhand-python-sdk
bash scripts/setup/setup_g1_bridge.sh
```

Install `pyrealsense2` for the onboard platform separately. On Arm systems,
the conda-forge package is usually the most reliable option.

Bring up both LinkerHand CAN interfaces before launch:

```bash
sudo /usr/sbin/ip link set can0 up type can bitrate 1000000
sudo /usr/sbin/ip link set can1 up type can bitrate 1000000
```

Calibrate OpenNeck with OpenNeck 0.2.0 and set `neck.config_path` if the
calibration file is not in the runtime working directory.

## 4. Start Teleopit

Run the dedicated onboard entry point and set the host IP, low-level tracking
policy, and G1 network interface:

```bash
python scripts/run/run_high_level_policy_sim2real.py \
  controller.policy_path=track.onnx \
  high_level_policy.endpoint=tcp://192.168.1.10:5555 \
  high_level_policy.task="pick up the object" \
  real_robot.network_interface=eth0
```

The protocol accepts action chunks from 1 to 50 frames. The production ACT
checkpoint uses a 50-frame horizon with `high_level_policy.replan_steps=3`.
For a 15-frame ReplayPolicy chunk, `replan_steps=15` remains valid. The request
stride must not exceed the horizon reported by the host.

The production camera contract is exactly RGB `uint8[480,640,3]` at 30 Hz.
`camera.source=test-pattern` exists only for controlled integration testing;
use `camera.source=realsense` for deployment.

## 5. Operator Flow

Keep the Unitree remote in hand. The runtime has only the formal robot modes
`IDLE`, `STANDING`, `POLICY`, and `DAMPING`.

| Control | Action |
|---------|--------|
| Unitree remote `Start` | Enter `STANDING` |
| Unitree remote `Y` | Request host-policy takeover |
| Unitree remote `B` | Pause or resume `POLICY` |
| Unitree remote `X` | Return to `STANDING` or cancel a pending request |
| Unitree remote `L1+R1` | Emergency transition to `DAMPING` |

After `Y`, Teleopit creates one entry session, establishes the current root
XY/yaw anchor, and requests its first chunk. The robot remains formally in
`STANDING` while waiting; there is no separate "policy starting" state. The
chunk's structure, finite values, quaternion, and absolute hardware ranges are
validated, while temporal root, yaw, and joint-reference jumps are accepted.
A valid first chunk enters `POLICY` directly. Entry does not align a candidate
reference, run a Kp ramp, pause/resume host requests, or create/reset a second
session. The scheduler's 50 Hz output limiter starts from the measured robot
reference captured when the session begins. A failure or timeout leaves the
robot on the normal standing reference.

Pause freezes the body reference and holds the last LinkerHand and OpenNeck
commands. Resume requests a fresh action chunk while continuing to hold the
paused pose. `X` stops the policy session and opens/centers the auxiliary
hardware as the runtime returns to `STANDING`.

A watchdog, host/network, camera, or policy-client fault enters this same
ordinary pause state and keeps the current body, hand, and neck commands. Once
the input path has recovered, press `B`; Teleopit holds the paused pose until a
fresh valid action chunk arrives, then resumes `POLICY`. The runtime never
enters `STANDING` automatically; `X` remains the manual transition.

## 6. Onboard Validation and Watchdog

Teleopit clips a G1 joint reference to the configured real-robot position
limits when the correction is at most `max_joint_projection_rad`, and clips
OpenNeck yaw/pitch commands to their configured degree ranges. It then rejects
a complete chunk if any frame violates the remaining contract. It never pads
or trims a malformed host result. Checks include:

- exact finite `float32[T,50]`, current session, and increasing source sequence;
- normalized root quaternion with temporal sign continuity;
- absolute root-height limits;
- G1 joint-position clipping to `real_robot.joint_pos_lower/upper`, with larger
  corrections rejected;
- LinkerHand closure `[0,1]`;
- OpenNeck yaw/pitch clipping to the configured degree ranges;
- observation/result age, source timestamp, and action horizon.

Reference continuity is not an acceptance condition. Root translation, root
yaw, and G1 joint-reference jumps are accepted at entry, inside a chunk, and
across chunks because a recorded pause/resume transition can intentionally be
discontinuous. The first valid chunk from the single entry session starts live
execution immediately. A malformed or stale first chunk, an out-of-range
non-joint field other than the projected OpenNeck angles, or an excessive joint
correction aborts entry.

Validated 30 Hz body references are interpolated and rate-limited locally at
50 Hz, including when latency skips source frames or a new chunk replaces the
old plan. The configured root displacement/XY speed, yaw-rate, and joint-rate
values are output limits, not chunk-rejection thresholds. The configured
grace period (three seconds by default) reuses the final validated reference
during transient inference or transport delays.
If no valid action remains, a network
exchange fails, or a required camera/client worker exits, Teleopit remains in
`POLICY`, enters the normal resumable pause state, and holds the latest body,
hand, and neck commands. After recovery, `B` requests resume; execution stays
paused until a fresh validated chunk arrives. Only `X` changes the mode to
`STANDING`.

The default safety envelope lives under `high_level_policy.safety` in
`high_level_policy_sim2real.yaml`. Adjust it only after checking the recorded
data, G1 joint limits, and the installed OpenNeck calibration.

## 7. Troubleshooting

**`Y` never enters `POLICY`:** check the host endpoint, firewall, server log,
`describe` schemas, message envelope, task, checkpoint manifest,
`replan_steps`, and the entry logs. Teleopit stays in `STANDING` until the single
entry session returns its first valid chunk.

**The first entry chunk is rejected or entry times out:** inspect the logged
contract error, joint ordering, absolute-reference convention, hardware ranges,
and host/network latency. Reference discontinuity alone does not reject a chunk.

**Policy runs briefly and becomes paused:** inspect timeout, inference
latency, stale-result, worker-exit, and safety-rejection logs. The low-level
50 Hz tracker does not block on host inference. Restore the failed input path,
then press `B` to resume.

**Pico does not connect:** this runtime intentionally does not start Pico. Stop
it and launch the Pico-specific `run_sim2real.py --config-name
pico4_sim2real` workflow instead.
