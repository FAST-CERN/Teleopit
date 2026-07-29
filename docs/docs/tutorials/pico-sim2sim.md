---
sidebar_position: 2
---

# VR Teleoperation in Simulation

Use Pico tracking to control a simulated G1 before connecting a physical robot.
Do not skip this step: it lets you fix headset, network and body-tracking
problems without putting hardware at risk.

## Before You Start

You need:

- a Pico 4 or Pico 4 Ultra with full-body tracking,
- the headset and the computer running Teleopit on the same network,
- the `pico4` install profile and `robots gmr ckpt bvh` assets, and
- a working result from
  [Run a Motion Controller in Simulation](offline-sim2sim).

## 1. Prepare the Headset

1. Download the headset APK from
   [pico-bridge Releases](https://github.com/BotRunner64/pico-bridge/releases).
2. Install it:

   ```bash
   adb install pico-bridge.apk
   ```

3. Open the pico-bridge app in the headset.
4. Turn on full-body tracking.

Teleopit uses pico-bridge 0.2.1. The receiver runs inside Teleopit on your
computer; there is no second relay program to start.

## 2. Check That the Computer Receives Pico Data

This diagnostic prints body-frame and connection information without starting
the robot controller:

```bash
python scripts/dev/test_pico_bridge.py --no-video
```

Move slightly and confirm that new valid frames continue to arrive. Press
`Ctrl+C` to stop the diagnostic.

If discovery chooses the wrong network address, pass the address that the
headset can reach:

```bash
python scripts/dev/test_pico_bridge.py \
    --no-video \
    --bridge-advertise-ip=192.168.1.20
```

## 3. Start the Simulation

```bash
python scripts/run/run_sim.py \
    --config-name pico4_sim \
    controller.policy_path=track.onnx
```

The robot intentionally starts in `STANDING`; live body tracking does not take
control until you ask for it.

## 4. Complete the First VR Session

1. Stand in a comfortable neutral pose and wait for stable tracking.
2. Press `Y` on the keyboard to enter `MOCAP`.
3. Move slowly at first and confirm that the simulated G1 follows.
4. Press `A` to pause, then press `A` again to resume.
5. Press `X` to return to `STANDING`.

| Key | Action |
|-----|--------|
| `Y` | Start whole-body control (`MOCAP`) |
| `A` | Pause or resume the current mocap session |
| `B` | Switch between `MOCAP` and arm-only control (`ARMS`) |
| `X` | Stop VR control and return to `STANDING` |
| `Q` | Quit |

The modes are simple:

- `STANDING`: the robot waits in its standing controller.
- `MOCAP`: the whole body follows the operator.
- `ARMS`: the body, waist and legs stay in the standing pose while both arms
  continue to follow the operator.

Each new `STANDING -> MOCAP` session recalibrates the live root pose. You may
turn to a new heading while standing, then enter `MOCAP` again.

:::tip Pausing is not the same as stopping VR control
`A` freezes and resumes the current mocap pose. Use `X` when you want to end the
session and return to `STANDING`.
:::

## Choose the Viewer Layout

Pico simulation opens the mocap, retarget and physics views by default. Use a
smaller layout when you no longer need all three:

```bash
# Physics result only
python scripts/run/run_sim.py \
    --config-name pico4_sim \
    controller.policy_path=track.onnx \
    viewers=sim2sim

# Headless
python scripts/run/run_sim.py \
    --config-name pico4_sim \
    controller.policy_path=track.onnx \
    viewers=none
```

## Optional Headset Video

To send the simulated `d435i_rgb` camera view back to the headset:

```bash
python scripts/run/run_sim.py \
    --config-name pico4_sim \
    controller.policy_path=track.onnx \
    input.video.enabled=true
```

Use `input.video.source=test-pattern` to check only the video connection.
Video failure disables the preview but does not stop tracking or control.

## Network Overrides

Most setups only need automatic discovery. Use these overrides when the
diagnostic shows a network problem:

```bash
# Advertise a specific host address to the headset
input.bridge_advertise_ip=192.168.1.20

# Disable discovery and bind explicitly
input.bridge_discovery=false
input.bridge_host=0.0.0.0
input.bridge_port=63901

# Wait longer for the first body frame
input.pico4_timeout=30
```

## Common Problems

| Symptom | What to do |
|---------|------------|
| `ImportError: pico_bridge` | Install the `pico4` profile again |
| Startup reports an old pico-bridge | Reinstall the profile so version 0.2.1 is used |
| No body frames arrive | Open the headset app, enable full-body tracking and check that UDP port 63901 is reachable |
| Discovery advertises the wrong address | Set `input.bridge_advertise_ip` to the computer address visible from the headset |
| G1 stays still in the viewer | Wait for stable tracking, then press `Y` |
| G1 follows only with its arms | Press `B` to leave `ARMS` and return to `MOCAP` |

Once this workflow is reliable, continue with
[VR Teleoperation on Unitree G1](pico-sim2real).
