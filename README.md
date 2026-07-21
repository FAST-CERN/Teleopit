<p align="center">
  <img src="assets/teleopit_logo.jpg" width="80" alt="Teleopit">
</p>

<h1 align="center">Teleopit</h1>

<p align="center">
  Lightweight, extensible whole-body teleoperation framework for humanoid robots.
  <br/>
  Real-time motion retargeting from BVH / Pico 4 VR to Unitree G1, in MuJoCo sim or on real hardware.
</p>

<p align="center">
  <a href="https://BotRunner64.github.io/Teleopit/">Documentation</a> &bull;
  <a href="https://BotRunner64.github.io/Teleopit/zh-Hans/">中文文档</a> &bull;
  <a href="https://BotRunner64.github.io/Teleopit/tutorials/pico-sim2sim">Pico Sim2Sim</a> &bull;
  <a href="https://BotRunner64.github.io/Teleopit/tutorials/pico-sim2real">Pico Sim2Real</a> &bull;
  <a href="https://BotRunner64.github.io/Teleopit/tutorials/training">Training</a>
</p>

---

## Quick Start — Minimal Sim2Sim

**1. Install**

```bash
pip install -e .
```

**2. Download assets**

```bash
pip install modelscope
python scripts/setup/download_assets.py --only robots gmr ckpt bvh
```

The canonical Unitree G1 robot model is downloaded to
`assets/robots/unitree_g1/g1_29dof.xml`. Training, sim2sim, retargeting, and FK
validation all use this same XML.

**3. Run**

```bash
python scripts/run/run_sim.py \
    controller.policy_path=track.onnx \
    input.bvh_file=data/sample_bvh/aiming1_subject1.bvh
```

You should see a MuJoCo viewer with the robot tracking the BVH motion.

To show the simulated D435i RGB camera view, add the explicit `camera` viewer:

```bash
python scripts/run/run_sim.py \
    controller.policy_path=track.onnx \
    input.bvh_file=data/sample_bvh/aiming1_subject1.bvh \
    'viewers=[sim2sim,camera]'
```

For sim2real, viewers are disabled by default. Add `viewers=retarget` to show
the retargeted reference in an optional MuJoCo window.

## Pico Motion Recording

Record many Pico clips as training-ready G1 motion NPZ files:

```bash
pip install -e '.[pico4]'
python scripts/run/record_pico_motion.py
```

The recorder starts the Pico receiver and live Retarget viewer before waiting
for clip names, so preview keeps running while the terminal is idle. Enter a
semantic clip name, then use `R` to start, `S` to save, `D` to discard, `N` for
a new name, and `Q` to quit. Saved clips are written to
`data/pico_motion/clips/` using the semantic label in the filename, with no
sidecar JSON.

Merge recorded clips into the standard HDF5 shard dataset:

```bash
python train_mimic/scripts/data/build_dataset.py \
    --spec data/pico_motion/pico_recorded.yaml --force
```

## Sim2Real HDF5 Recording

Pico sim2real can also record manual HDF5 episodes from the real G1:

```bash
pip install -e '.[recording]'
# If you use RealSense video, install pyrealsense2 manually for your platform.
# On Arm machines, prefer conda-forge:
# conda install -c conda-forge pyrealsense2
python scripts/run/run_sim2real.py --config-name sim2real_record \
    controller.policy_path=track.onnx \
    recording.task="walk forward"
```

Recording uses the terminal controls `R` start, `S` save, `D` discard, and `Q`
shutdown. `STANDING`, `MOCAP`, `ARMS`, and paused mocap can be recorded. Saved
episodes are written under `data/recordings/sim2real_hdf5/data/`, with compressed
MP4 files under `videos/d435i_rgb/`. `schema.json` records the FPS, robot, hand,
and neck types, plus feature shapes, names, and groups. `episodes.jsonl` maps each episode
to its HDF5/video files and stores its editable task prompt. HDF5 contains only
frame-aligned arrays: `observation.state(68)`, scalar `observation.mode`, and
`action(36)` as the aligned reference qpos consumed by the motion tracker.
`action.hand(12)` is present exactly when LinkerHand control is enabled, and
`action.neck(2)` contains the latest mechanically clamped OpenNeck
`[yaw_deg, pitch_deg]` target when OpenNeck control is enabled.
Recording is non-critical: an incompatible output schema stops only the
recording worker while G1 control continues. Episodes interrupted before their
manifest entry is committed are discarded on the next recording startup.
RealSense frame timeouts and disconnects trigger background camera reconnection
without stopping Pico input or G1 control. Recording requires a fresh camera
frame to start and discards an active episode after one second without video;
press `R` again after the camera recovers. If the entire Pico input worker exits,
G1 control remains active and holds the latest command so the operator can use
the Unitree remote to return to `STANDING` or request `DAMPING`.

Review saved episodes in a synchronized read-only web UI:

```bash
pip install -e '.[review]'
python scripts/view/view_recording.py \
    --recording data/recordings/sim2real_hdf5
```

The reviewer validates the manifest, HDF5 arrays, and MP4 frame count before
playback. It shows D435i video beside the observed G1 pose with a translucent
green reference overlay, plus mode, joint-tracking, LinkerHand, and OpenNeck
timelines. Because recordings do not contain measured root XYZ, the observed
pose is anchored to the reference root position; joint and root-orientation
comparisons remain valid.

## Host High-Level Policy Deployment

Teleopit can run a host-served ReplayPolicy or LeRobot ACT policy through a
dedicated onboard runtime. The host policy remains in the independent
`lerobot-teleopit` repository/environment; Teleopit receives canonical 50D
reference chunks over ZeroMQ, validates and interpolates them onboard, and
rate-limits plan switches at 50 Hz before passing the 36D body reference
through the existing motion tracker. The host never sends G1 motor commands.

Pico and high-level-policy deployment use separate scripts. The policy runtime
does not start PicoBridge, GMR, or the Pico reference worker:

```bash
python scripts/run/run_high_level_policy_sim2real.py \
    controller.policy_path=track.onnx \
    high_level_policy.endpoint=tcp://192.168.1.10:5555 \
    high_level_policy.task="pick up the object" \
    real_robot.network_interface=eth0
```

Use the Unitree remote: `Start` enters `STANDING`, `Y` requests policy
takeover, `B` pauses/resumes, `X` returns to `STANDING`, and `L1+R1` enters
`DAMPING`. Policy entry remains an internal `STANDING` phase with no separate
starting mode: Teleopit validates a candidate chunk, holds its first body
reference through one motion-tracker Kp ramp, then creates one fresh host
session. A valid chunk from that session is required before entering `POLICY`;
Replay therefore restarts from its configured start frame and ACT recomputes
from the post-ramp observation. The 50 Hz output limiter starts from the held
reference, not the tracker's measured joint pose. Temporal reference jumps are
accepted so recorded pause/resume transitions can be replayed, then rate-limited
on output. OpenNeck yaw/pitch values are clipped to the configured degree ranges
before scheduling, so a neck-only overshoot does not reject the action chunk.
Entry failure returns to `STANDING`.
Invalid/stale live chunks and watchdog expiry cannot block the local control
loop and instead pause `POLICY` while holding the last reference. Host/network
failure and loss of a required camera/client worker use the same ordinary pause
state as remote `B`; after recovery, press `B` to resume on a fresh valid chunk.
Only `X` returns active `POLICY` to `STANDING`.

The current client/server code and protocol tests define the network message
structure. During active development, Teleopit and `lerobot-teleopit` must be
updated together. Their only shared data file is `hand_calibration.json`, which
contains the LinkerHand O6 open/close calibration. See the
[host-policy deployment tutorial](https://BotRunner64.github.io/Teleopit/tutorials/high-level-policy-sim2real)
for the 68D observation, 50D action layout, safety envelope, host startup, and
operator procedure.

## OpenNeck Active Vision

Pico sim2real can drive the optional OpenNeck two-axis active-vision gimbal from
the same Pico receiver used for whole-body control:

```bash
pip install -e '.[openneck]'
python scripts/run/run_sim2real.py --config-name pico4_sim2real \
    controller.policy_path=track.onnx \
    neck.enabled=true \
    neck.port=/dev/ttyACM0
```

`neck.enabled=true` requires `input.provider=pico4`. The neck worker reuses the
existing Teleopit Pico receiver and does not start another `PicoBridge` or
camera pipeline. The neck path reads the independent HMD
`PicoFrame.head.rotation` and maps it relative to `Body.Spine3` from the same
source frame. It never uses the full-body tracker's `Body.Head` skeleton joint,
whose model constraints can under-report extreme head pitch. The mapper uses a
fixed neutral pose and no neck-side EMA, so tracking startup does not require
the operator to face straight ahead. After the dead zone, Teleopit multiplies
the relative pitch by `neck.pitch_gain` (default `1.4`) to compensate for the
robot camera geometry; yaw remains one-to-one. It then sends physical angles
through the OpenNeck 0.2.0 `move_deg()` API. OpenNeck converts those angles for
its direct-drive servos and clips them to the calibrated mechanical step
limits. Positive yaw turns left and positive pitch looks up.

OpenNeck 0.2.0 uses an angle-based calibration file and rejects the previous
normalized configuration fields. Re-run `openneck calibrate` before enabling
the neck worker, and set `neck.config_path` when the calibration file is not in
the runtime working directory.

## Documentation

Full docs at **[BotRunner64.github.io/Teleopit](https://BotRunner64.github.io/Teleopit/)**, covering installation profiles, all tutorials, configuration reference, and architecture.

## Changelog

### v0.4.0 (2026-06-25)

- Improved Pico realtime control with pico-bridge 0.2.1, `ARMS` mode, armed sim2real mocap entry, and retargeter-preserving pause/arms resets.
- Added optional LinkerHand L6/O6 sim2real control, including Pico gripper input and low-latency L6/O6 `vr_hand_pose`.
- Added manual Pico sim2real HDF5 recording and an interactive Pico motion recorder for training NPZ clips.
- Refined the training data path with minimal HDF5 shards, explicit precompute, rewind sampling, and updated tracking rewards.

### v0.3.0 (2026-05-12)

- Consolidated realtime input around pico-bridge 0.2.0 and removed the old ZMQ/onboard Pico path.
- Unified sim/sim2real reference buffering, resume realignment, and velocity smoothing.
- Added UDP BVH realtime input, online sim config, multi-viewer support, and fixed camera viewing.
- Split sim2real reference/safety runtime modules and updated the G1 MuJoCo camera asset.

### v0.2.0 (2026-04-03)

- Added Pico 4 teleoperation through pico-bridge and the G1 Bridge SDK.
- Added offline playback keyboard controls, Pico sim2sim mode control, and a standalone standing controller.
- Improved realtime mocap buffering/catch-up and upgraded the released model to the 30k checkpoint.

### v0.1.1 (2026-03-28)

- Dataset shard-only refactor
- External asset management (ModelScope), repository slimming

### v0.1.0 (2026-03-25)

- Initial public release: General-Tracking-G1 training, ONNX sim2sim inference, Pico 4 VR teleoperation, Unitree G1 hardware deployment

## License

[Apache 2.0](LICENSE)
