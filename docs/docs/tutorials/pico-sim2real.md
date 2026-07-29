---
sidebar_position: 3
---

# VR Teleoperation on Unitree G1

This guide moves the Pico workflow from MuJoCo to a physical Unitree G1. The
motion input is the same; the important new pieces are the G1 network, the DDS
bridge and safe operator transitions.

:::danger Keep the Unitree remote in your hand
Use `L1+R1` to enter `DAMPING` whenever motion is unexpected. Start with clear
space around the robot and an operator ready to support or stop it.
:::

## Before You Start

Do not continue until all of these are true:

- [VR Teleoperation in Simulation](pico-sim2sim) works reliably.
- You installed the `pico4` profile and built `g1_bridge_sdk` as described in
  [Installation](../getting-started/installation).
- `track.onnx`, robot assets and GMR assets are present.
- The computer running Teleopit has a wired DDS connection to the G1.
- No other program is commanding the robot.

Teleopit may run on an external PC connected to G1 by Ethernet or on the G1
onboard computer. Pico still connects directly to the machine running Teleopit.

## 1. Find the G1 Network Interface

List the Linux interfaces:

```bash
ip -br link
```

For a wired PC, use the Ethernet interface connected to G1, such as
`enp130s0`. On the onboard computer, it is usually `eth0`.

The value is passed as:

```text
real_robot.network_interface=enp130s0
```

This interface is for Unitree DDS. If Pico discovery selects the wrong Wi-Fi or
Ethernet address, set `input.bridge_advertise_ip` separately.

## 2. Check Standing Control First

Run the same standing controller used by sim2real before adding Pico:

```bash
python scripts/run/standalone_standing.py \
    --policy track.onnx \
    --network-interface enp130s0 \
    --dry-run
```

The dry run checks state reception and policy timing without sending motor
commands. Then repeat without `--dry-run` in a safe hardware setup:

```bash
python scripts/run/standalone_standing.py \
    --policy track.onnx \
    --network-interface enp130s0
```

If this fails, stop here and use the
[Standalone Standing reference guide](standalone-standing). Pico cannot fix a
G1 bridge or policy problem.

## 3. Start Pico Sim2Real

Wired PC example:

```bash
python scripts/run/run_sim2real.py \
    --config-name pico4_sim2real \
    controller.policy_path=track.onnx \
    real_robot.network_interface=enp130s0
```

Onboard example:

```bash
python scripts/run/run_sim2real.py \
    --config-name pico4_sim2real \
    controller.policy_path=track.onnx \
    real_robot.network_interface=eth0
```

Starting the process does not immediately hand control to Pico.

## 4. Hand Over Control Deliberately

1. Press remote `Start` to enter `STANDING`.
2. Wait until the robot is stable and Pico tracking is valid.
3. Stand in a neutral pose with room to move.
4. Press remote `Y` to enter `MOCAP`.
5. Begin with small, slow movements.
6. Press remote `X` when you want to return to `STANDING`.

| Control | Action |
|---------|--------|
| Unitree remote `Start` | Enter `STANDING` |
| Unitree remote `Y` | Start whole-body VR control (`MOCAP`) |
| Unitree remote `B` | Pause or resume the current mocap session |
| Pico/controller `A` | Pause or resume the current mocap session |
| Pico/controller `B` | Switch between whole-body `MOCAP` and arm-only `ARMS` |
| Unitree remote `X` | End VR control and return to `STANDING` |
| Unitree remote `L1+R1` | Emergency stop (`DAMPING`) |

Teleopit checks several consecutive Pico frames before entering `MOCAP`. If the
check fails, the robot remains in `STANDING`.

### Pause and Resume

Pause holds the current reference pose; it does not return the robot to
`STANDING`. Resume rebuilds the live alignment from the current operator pose.
Resume while standing still and close to the held pose. Use remote `X` instead
when you want to end the VR session.

### What Happens if Pico or Video Fails?

Pico input and camera preview are non-critical workers. If Pico input stops, the
G1 control loop keeps the last safe command and the Unitree remote remains
available. A RealSense timeout disables or reconnects video without stopping
body control. Use remote `X` or `L1+R1`; do not wait for an automatic mode
change.

## Optional: LinkerHand Control

Skip this section unless LinkerHand hardware is connected. Install the local
hand packages from [Installation](../getting-started/installation), then bring
up both CAN interfaces:

```bash
sudo /usr/sbin/ip link set can0 up type can bitrate 1000000
sudo /usr/sbin/ip link set can1 up type can bitrate 1000000
```

Test the hands before starting the robot runtime:

```bash
python scripts/dev/test_linkerhand.py \
    --driver linkerhand_o6 \
    --hand-type both \
    --left-can can0 \
    --right-can can1
```

Enable O6 hand-pose control by adding:

```text
hands.enabled=true
hands.driver=linkerhand_o6
hands.mode=vr_hand_pose
hands.linkerhand_o6.left_can=can0
hands.linkerhand_o6.right_can=can1
```

Use `hands.mode=gripper` for trigger-based open/close control.
`linkerhand_l6` is also supported; use the matching
`hands.linkerhand_l6.*` CAN keys. Hand control remains active in all robot
modes, and runtime failure opens the hands.

## Optional: OpenNeck Active Vision

Skip this section unless OpenNeck is installed and calibrated:

```bash
pip install -e '.[openneck]'
openneck calibrate
```

Enable it in the main command:

```text
neck.enabled=true
neck.port=/dev/ttyACM0
```

OpenNeck follows the Pico HMD relative to the operator's upper body. It uses the
same Pico receiver as body control and does not start another PicoBridge.

## Optional: RealSense Preview in the Headset

Install `pyrealsense2`, then add:

```text
input.video.enabled=true
input.video.device=<optional-realsense-serial>
```

RealSense reconnects in the background after a timeout. Camera failure does not
stop Pico tracking or G1 control.

## Optional: Record and Review Episodes

Recording requires the `recording` profile and a fresh RealSense RGB frame:

```bash
python scripts/run/run_sim2real.py \
    --config-name sim2real_record \
    controller.policy_path=track.onnx \
    real_robot.network_interface=enp130s0 \
    recording.task="walk forward"
```

| Terminal key | Action |
|--------------|--------|
| `R` | Start an episode |
| `S` | Save the active episode |
| `D` | Discard the active episode |
| `Q` | Shut down |

If fresh video is missing for one second, the active episode is discarded while
robot control continues. Start a new episode manually after video recovers.

Review saved data with:

```bash
pip install -e '.[review]'
python scripts/view/view_recording.py \
    --recording data/recordings/sim2real_hdf5
```

The reviewer synchronizes camera video, observed/reference G1 poses and optional
hand/neck signals. The recording layout and field definitions are documented
in [Dataset Reference](../reference/dataset).

## Common Problems

| Symptom | What to do |
|---------|------------|
| No `LowState` arrives | Check the Ethernet cable and `real_robot.network_interface` |
| `g1_bridge_sdk` cannot import | Re-run `scripts/setup/setup_g1_bridge.sh` in the active environment |
| `Start` cannot enter standing control | Stop other Unitree modes and programs, then try again |
| `Y` does not enter `MOCAP` | Keep Pico tracking visible and stable; inspect mocap validation logs |
| Pausing does not return to standing | This is expected; use remote `X` |
| Pico cannot discover Teleopit | Set `input.bridge_advertise_ip` to an address reachable from the headset |
| LinkerHand does not move | Check `hands.enabled`, driver/mode, CAN state and the standalone hand test |
| RealSense is unavailable on Arm | Install `pyrealsense2` from conda-forge |

## Other G1 Workflows

The main tutorial path is Pico VR. These focused guides remain available for
less common bring-up and deployment work:

- [Standalone Standing Test](standalone-standing)
- [BVH Playback on Unitree G1](bvh-sim2real)
- [Host Policy Deployment on Unitree G1](high-level-policy-sim2real)
