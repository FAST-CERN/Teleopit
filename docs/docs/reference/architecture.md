---
sidebar_position: 1
---

# Architecture

This page collects the runtime pipeline, supported boundaries and exact
dimensions that are intentionally omitted from the task-based user guides.

## Pipeline

```text
InputProvider (BVH file / Pico4)
    -> Retargeter (GMR)
    -> ObservationBuilder (167D)
    -> Controller (dual-input TemporalCNN ONNX)
    -> Robot (MuJoCo sim or Unitree G1)
```

Offline/online inference is assembled by `teleopit/runtime/` and `teleopit/pipeline.py`. The hardware state machine runs through the process-isolated runtime in `teleopit/sim2real/mp/`. Training is provided by `train_mimic/`.

## Full-Embodiment Pico Path

One Pico frame can feed three independent control paths:

```text
Pico full-body tracking
  -> GMR retargeting -> tracking policy -> G1 whole-body joints

Pico hand tracking or controller input
  -> Teleopit hand adapter -> somehand or gripper mapping -> LinkerHand L6/O6

Pico HMD rotation + same-frame Spine3 rotation
  -> relative yaw/pitch mapping -> OpenNeck
```

Whole-body control is the required path. Hands and OpenNeck are optional
process-isolated workers; their failure must not stop G1 body control. All
three paths reuse the same in-process PicoBridge receiver.

Host-served imitation policies use a second, independent deployment path:

```text
lerobot-teleopit host environment
  policy server -> strict ZeroMQ/msgpack messages
                       |
Teleopit onboard environment
  RealSense/state -> non-critical client worker -> validated action scheduler
  -> existing 50 Hz motion tracker -> G1 joint-angle targets
  -> dedicated LinkerHand O6 and OpenNeck workers
```

The host and onboard environments share semantic data and one identical
`hand_calibration.json`; they do not import each other's Python packages. The
current client/server code and protocol tests define the network structure, so
both repositories must change together during active development. Pico
teleoperation and host-policy deployment also have separate run scripts and
process assemblies.

## Code Structure

```text
configs / scripts
    -> runtime
    -> interfaces + pipeline state machines
    -> adapters (inputs / retargeting / controller / robot / recording)

train_mimic/scripts
    -> train_mimic/app.py
    -> single task registry / env builder / runner cfg
    -> mjlab / rsl_rl

train_mimic/scripts/data
    -> train_mimic/data/dataset_builder.py
    -> dataset_lib / motion_fk / convert_pkl_to_npz
```

## Core Boundaries

| Module | Role |
|--------|------|
| `teleopit/interfaces.py` | Stable protocols: InputProvider, Retargeter, Controller, Robot, ObservationBuilder |
| `teleopit/runtime/` | Config parsing, path normalization, component assembly, CLI validation |
| `teleopit/pipeline.py` | Lightweight facade for offline sim |
| `teleopit/sim2real/mp/` | Process-isolated sim2real state machine, IPC, and robot-control loop |
| `teleopit/high_level_policy/` | Host-policy protocol, session-local frame transform, validation, and 30-to-50 Hz scheduler |
| `teleopit/controllers/observation.py` | ObservationBuilder |
| `teleopit/controllers/rl_policy.py` | Accepts dual-input ONNX whose observation dimension matches the runtime builder |
| `train_mimic/app.py` | Shared train/play/benchmark assembly |
| `train_mimic/tasks/tracking/config/` | Single task registration (`General-Tracking-G1`) |
| `train_mimic/data/dataset_builder.py` | Sole official dataset construction entry |

## Technical Specifications

| Spec | Value |
|------|-------|
| Supported robot | Unitree G1, 29 actuated joints |
| Simulator | MuJoCo |
| Motion retargeting | GMR (General Motion Retargeting) |
| Policy / PD rates | 50 Hz / 200 Hz |
| Training task | `General-Tracking-G1` |
| Inference observation | `velcmd_history` (167D) |
| ONNX signature | Dual-input `obs` (167D) + `obs_history` |
| Policy action | 29D joint offsets from `default_dof_pos` |
| Actor/Critic | TemporalCNN (2048, 1024, 512, 256, 128) |
| Training sampling | Default `rewind`; also supports `uniform`; playback uses `start`; benchmark pins exact clips and disables clip-end resampling |
| Training `window_steps` | `[0]` |
| Data format | Minimal recursive HDF5 shards (`shard_*.h5`) |
| Optional hands | LinkerHand L6 or O6, gripper or Pico hand-pose input |
| Optional active vision | OpenNeck yaw/pitch in physical degrees |
| Host-policy observation | JPEG RGB + `observation.state(68)` |
| Host-policy action | `float32[T,50]` canonical reference at 30 Hz |
| Host-policy body control | 36D root/joint reference through the existing 50 Hz motion tracker |

## Constraints

- `controller.policy_path` must be explicitly provided and the file must exist
- Offline BVH runs require explicit `input.bvh_file`
- `viewers` is the sole viewer configuration entry
- Observation/ONNX dimension mismatch causes immediate startup error
- sim2real also requires a dual-input ONNX whose observation dimension matches the runtime builder
- Host-policy message-envelope or schema mismatches are rejected while the robot remains in `STANDING`
- Host action chunks are validated and interpolated onboard; the host cannot bypass the motion tracker or send motor commands
- Policy entry remains internal to `STANDING` only while one host session waits for its first valid chunk; that chunk enters `POLICY` directly, with no candidate alignment, entry Kp ramp, or second session/reset, and the 50 Hz limiter starts from the measured robot reference captured at session start
- Temporal root, yaw, and joint-reference discontinuities are accepted at chunk boundaries and inside chunks, then rate-limited at the 50 Hz scheduler output so recorded pause/resume transitions remain usable

## Public Surface

**Stable run modes:** offline sim2sim, offline sim2real playback, Pico4 sim2sim,
G1 sim2real, independent host-policy G1 sim2real

**Stable training entry points:** `train.py`, `play.py`, `benchmark.py`, `save_onnx.py`

**Stable data entry points:** `build_dataset.py`, `precompute_dataset.py`
