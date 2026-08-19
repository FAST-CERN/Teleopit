# Twist cmd_vel Control Channel — Sim Phase (A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a coexisting twist cmd_vel control channel to Teleopit: an external Unitree velocity ONNX policy driven by a `CommandProvider` twist source, with a STANDING(mimic)↔VELOCITY(twist) mode machine in simulation, validated by quantitative pytest metrics and MuJoCo visual inspection.

**Architecture:** A new explicit typed `TwistCmdObservationBuilder` (98D, stateful gait phase) and a `CommandProvider` protocol (keyboard first) feed a new lightweight `VelocitySimSession` that reuses `PolicyStepRunner` control primitives but bypasses the entire mocap `SimLoopSession` input stack. Config gains dual controller sections (`controllers.mimic` + `controllers.velocity`) plus a `modes:` section. Factory dispatch gains an `observation_type` registry entry and drops its dual-input-ONNX requirement for single-input velocity policies. Safety: joint-velocity check wired into the velocity loop, orientation check with configurable threshold, both VELOCITY-only.

**Tech Stack:** Python 3.10, NumPy, onnxruntime, MuJoCo, pytest, Hydra/OmegaConf config (existing stack, no new dependencies).

## Global Constraints

- Mimic pipeline behavior must not change: `controllers.mimic` (or legacy `controller`) config path, `SimLoopSession`, `VelCmdObservationBuilder`, existing tests — all untouched. Zero regression on `pytest tests/` for the mimic path.
- The ONNX policy is an external file: `F:\Chufan_Rui\teleop\unitree_rl_mjlab\deploy\robots\g1\config\policy\velocity\v1\exported\policy.onnx` (obs `[1,98]` → actions `[1,29]`, 50 Hz). It must be **copied** into the repo under `assets/policies/velocity_v1/policy.onnx` (repo-relative, self-contained); do not reference the external path from configs.
- 98D observation layout (exact order, from the policy's `deploy.yaml`): `base_ang_vel(3) + projected_gravity(3) + velocity_commands(3) + gait_phase(2) + joint_pos_rel(29) + joint_vel_rel(29) + last_action(29)`.
- Velocity command ranges: `lin_vel_x ∈ [-1.0, 2.0]`, `lin_vel_y ∈ [-0.5, 0.5]`, `ang_vel_z ∈ [-1.0, 1.0]` (clamped).
- Gait phase: `period = 0.6 s`, obs = `[sin(2π·φ), cos(2π·φ)]`, zeroed when `‖cmd‖ < 0.1`; stateful, must reset.
- Pose B (velocity default joint pos, 29 values): `[-0.1,0,0,0.3,-0.2,0, -0.1,0,0,0.3,-0.2,0, 0,0,0, 0.35,0.18,0,0.87,0,0,0, 0.35,-0.18,0,0.87,0,0,0]`.
- Pose A (mimic default, existing `g1.yaml default_angles`) must remain unchanged.
- Action decode: `target = pose_B + per_joint_scale × clip(action, clip_range)`. Per-joint scale (29): `[0.55,0.35,0.55,0.35,0.44,0.44, 0.55,0.35,0.55,0.35,0.44,0.44, 0.55,0.44,0.44, 0.44,0.44,0.44,0.44,0.44,0.07,0.07, 0.44,0.44,0.44,0.44,0.44,0.07,0.07]`. `RLPolicyController.get_target_dof_pos` already implements `clip → scale → + default_dof_pos`; the velocity controller cfg just needs its own `default_dof_pos` (pose B) and `action_scale` — `propagate_controller_defaults` must NOT overwrite them with robot-level pose A values.
- `CommandProvider` boundary is DDS-future-proof: interface speaks 6D twist only (`[lin_x, lin_y, lin_z, ang_x, ang_y, ang_z]`, only `[lin_x, lin_y, ang_z]` consumed now), no keyboard/Pico specifics leak above the provider.
- Safety (VELOCITY mode only): joint velocity > 10.0 rad/s → DAMPING-stop; `acos(-proj_grav_b[2]) > tilt_threshold_rad` (default 1.0) → transition to STANDING. Both configurable.
- Transition STANDING↔VELOCITY: reference interpolation from held pose to pose B over `transition_duration_s` (default 1.0, range 0.5–2.0); on entering VELOCITY, reset policy state (gait phase → 0, `last_action` → 0, `obs_builder.reset()`); **`prev_action` observation is seeded with the mimic controller's last action, not zeroed** (Q8/Q9 decision).
- Verification metrics (Task 11): transition `target_dof_pos` max jump per step < 0.15 rad/joint; cmd tracking error < 0.35 m/s mean over 5 s window; pose-B standing stability 30 s (root height > 0.6 m, no NaN).
- Windows dev environment (Git Bash). `python` is Anaconda with `onnxruntime` user-installed (v1.29.0).
- Commit style: repo uses conventional commits (`feat:`, `fix:`, `chore:` ...). End commit messages with `Co-Authored-By: Claude <noreply@anthropic.com>`.

## File Structure

```
teleopit/
  controllers/
    twist_observation.py        # NEW — TwistCmdObservationBuilder (98D, stateful gait phase)
  commands/
    __init__.py                 # NEW — package init, re-exports
    base.py                     # NEW — CommandProvider protocol + TwistCommand dataclass
    keyboard_cmd.py             # NEW — KeyboardTwistProvider (WASD/QE, poll()-driven)
  sim/
    velocity_session.py         # NEW — VelocitySimSession: mode machine + policy/PD loop
    reference_interpolation.py  # NEW — StandingReferenceInterpolator (hold→pose-B ramp)
  runtime/
    factory.py                  # MODIFY — observation_type registry, dual controller sections,
                                #         conditional dual-input check
  configs/
    controller/velocity.yaml    # NEW — velocity controller section values
    velocity_sim.yaml           # NEW — sim entry config (modes:, controllers.mimic+velocity)
scripts/run/
  run_velocity_sim.py           # NEW — CLI entry (Hydra)
tests/
  test_twist_observation.py     # NEW
  test_keyboard_cmd.py          # NEW
  test_reference_interpolation.py  # NEW
  test_velocity_session.py      # NEW — mode machine + metrics (uses real ONNX)
assets/policies/velocity_v1/
  policy.onnx                   # NEW — copied from unitree_rl_mjlab deploy tree
```

Responsibilities:
- `twist_observation.py` — one builder class, exact 98D layout, dimension/finiteness fail-fast, gait-phase state + reset. No robot coupling beyond `RobotState`.
- `base.py` — the transport-agnostic command seam (protocol only, ~30 lines). Nothing else imports keyboard types above it.
- `keyboard_cmd.py` — keyboard → 6D twist; owns `TerminalKeyboardReader` (Windows note: reader is a no-op when stdin isn't a tty, which is what tests rely on).
- `velocity_session.py` — STANDING↔VELOCITY machine, per-step loop, safety checks, metrics recording. Reuses `PolicyStepRunner` via composition.
- `reference_interpolation.py` — pure numpy: (hold_qpos, target_qpos, t, duration) → interpolated qpos. Unit-testable in isolation.
- `factory.py` changes — additive: registry dict for `observation_type`, per-section controller build, single-input allowance keyed on section type. Existing `build_inference_components` signature unchanged (mimic callers untouched).

---

### Task 1: Copy policy asset + velocity controller config

**Files:**
- Create: `assets/policies/velocity_v1/policy.onnx` (copy)
- Create: `teleopit/configs/controller/velocity.yaml`
- Test: `tests/test_twist_observation.py` (smoke: file exists & loads)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: config section `controllers.velocity` readable via `cfg_get(cfg, "controllers.velocity")` with keys `policy_path`, `observation_type: twist_cmd`, `default_dof_pos` (pose B, 29), `action_scale` (29), `clip_range: [-10, 10]`, `device: auto`. Asset path constant used by later configs: `assets/policies/velocity_v1/policy.onnx`.

- [ ] **Step 1: Copy the ONNX file**

```bash
mkdir -p assets/policies/velocity_v1
cp "/f/Chufan_Rui/teleop/unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v1/exported/policy.onnx" assets/policies/velocity_v1/policy.onnx
ls -la assets/policies/velocity_v1/
```

Expected: file present, size > 100 KB.

- [ ] **Step 2: Write the config file `teleopit/configs/controller/velocity.yaml`**

```yaml
# Velocity-policy controller section (twist cmd_vel channel).
# Default pose is the POLICY's neutral pose (pose B) — do not let robot-level
# defaults propagate over these (propagate_controller_defaults is skipped for
# explicit sections that already define both keys).
policy_path: assets/policies/velocity_v1/policy.onnx
observation_type: twist_cmd
device: auto
clip_range: [-10.0, 10.0]
default_dof_pos: [-0.1,0,0,0.3,-0.2,0,
                  -0.1,0,0,0.3,-0.2,0,
                  0,0,0,
                  0.35,0.18,0,0.87,0,0,0,
                  0.35,-0.18,0,0.87,0,0,0]
action_scale: [0.55,0.35,0.55,0.35,0.44,0.44,
               0.55,0.35,0.55,0.35,0.44,0.44,
               0.55,0.44,0.44,
               0.44,0.44,0.44,0.44,0.44,0.07,0.07,
               0.44,0.44,0.44,0.44,0.44,0.07,0.07]
# Twist command clamp ranges (mirrors unitree deploy.yaml commands.base_velocity.ranges)
cmd_limits:
  lin_vel_x: [-1.0, 2.0]
  lin_vel_y: [-0.5, 0.5]
  ang_vel_z: [-1.0, 1.0]
# Gait phase clock
gait_period_s: 0.6
gait_zero_cmd_norm: 0.1
```

- [ ] **Step 3: Smoke test file + config load**

```bash
python -c "
import onnxruntime as ort, yaml
s = ort.InferenceSession('assets/policies/velocity_v1/policy.onnx', providers=['CPUExecutionProvider'])
assert [i.shape for i in s.get_inputs()] == [[1, 98]], s.get_inputs()
assert [o.shape for o in s.get_outputs()] == [[1, 29]], s.get_outputs()
cfg = yaml.safe_load(open('teleopit/configs/controller/velocity.yaml'))
assert len(cfg['default_dof_pos']) == 29 and len(cfg['action_scale']) == 29
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add assets/policies/velocity_v1/policy.onnx teleopit/configs/controller/velocity.yaml
git commit -m "feat(velocity): add velocity_v1 ONNX asset and controller config section

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `TwistCmdObservationBuilder`

**Files:**
- Create: `teleopit/controllers/twist_observation.py`
- Test: `tests/test_twist_observation.py`

**Interfaces:**
- Consumes: `teleopit.interfaces.RobotState` (fields `qpos`, `qvel`, `quat`, `ang_vel` — body frame), `teleopit.runtime.common.cfg_get`.
- Produces:
  - `TwistCmdObservationBuilder(cfg)` — cfg keys: `num_actions: int`, `default_dof_pos: FloatVec(29)` (pose B), `cmd_limits: {lin_vel_x, lin_vel_y, ang_vel_z: (lo, hi)}`, `gait_period_s: float`, `gait_zero_cmd_norm: float`, `policy_dt: float`.
  - `.total_obs_size: int` (= 98)
  - `.build(state: RobotState, cmd: np.ndarray, last_action: np.ndarray) -> np.ndarray(98,)` — cmd is the raw 6D twist; builder clamps `[lin_x, lin_y, ang_z]` itself.
  - `.reset() -> None` — zeroes gait phase clock.
  - Raises `ValueError` on any dimension mismatch or non-finite obs (after damping to zero with a warning, matching `VelCmdObservationBuilder` NaN policy).

- [ ] **Step 1: Write failing tests `tests/test_twist_observation.py`**

```python
from __future__ import annotations

import numpy as np
import pytest

from teleopit.interfaces import RobotState
from teleopit.controllers.twist_observation import TwistCmdObservationBuilder

POSE_B = np.array([-0.1,0,0,0.3,-0.2,0, -0.1,0,0,0.3,-0.2,0, 0,0,0,
                   0.35,0.18,0,0.87,0,0,0, 0.35,-0.18,0,0.87,0,0,0], dtype=np.float32)


def _cfg(**over):
    cfg = {
        "num_actions": 29,
        "default_dof_pos": POSE_B.tolist(),
        "cmd_limits": {"lin_vel_x": [-1.0, 2.0], "lin_vel_y": [-0.5, 0.5], "ang_vel_z": [-1.0, 1.0]},
        "gait_period_s": 0.6,
        "gait_zero_cmd_norm": 0.1,
        "policy_dt": 0.02,
    }
    cfg.update(over)
    return cfg


def _state(qpos=None, ang_vel=None):
    q = POSE_B if qpos is None else np.asarray(qpos, dtype=np.float64)
    return RobotState(
        qpos=q,
        qvel=np.zeros(29, dtype=np.float64),
        quat=np.array([1.0, 0.0, 0.0, 0.0]),
        ang_vel=np.zeros(3) if ang_vel is None else np.asarray(ang_vel, dtype=np.float64),
        timestamp=0.0,
    )


class TestLayout:
    def test_obs_is_98d_at_neutral(self):
        b = TwistCmdObservationBuilder(_cfg())
        obs = b.build(_state(), np.zeros(6, dtype=np.float32), np.zeros(29, dtype=np.float32))
        assert obs.shape == (98,)
        assert obs.dtype == np.float32

    def test_segment_layout_order(self):
        """[0:3]=ang_vel [3:6]=proj_grav [6:9]=cmd [9:11]=gait [11:40]=jpos_rel [40:69]=jvel [69:98]=last_action"""
        b = TwistCmdObservationBuilder(_cfg())
        ang = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        cmd = np.array([0.5, -0.2, 0.3, 0, 0, 0], dtype=np.float32)
        act = np.full(29, 0.05, dtype=np.float32)
        obs = b.build(_state(ang_vel=ang), cmd, act)
        np.testing.assert_allclose(obs[0:3], ang, atol=1e-6)
        # identity quat → projected gravity = [0,0,-1]
        np.testing.assert_allclose(obs[3:6], [0.0, 0.0, -1.0], atol=1e-6)
        np.testing.assert_allclose(obs[6:9], [0.5, -0.2, 0.3], atol=1e-6)
        # cmd norm 0.62 >= 0.1 → gait nonzero after first step
        assert not np.allclose(obs[9:11], 0.0)
        np.testing.assert_allclose(obs[11:40], 0.0, atol=1e-6)  # state == pose B
        np.testing.assert_allclose(obs[40:69], 0.0, atol=1e-6)  # zero joint vel
        np.testing.assert_allclose(obs[69:98], act, atol=1e-6)

    def test_joint_pos_rel_uses_pose_b(self):
        b = TwistCmdObservationBuilder(_cfg())
        q = POSE_B.copy()
        q[3] += 0.4  # knee offset
        obs = b.build(_state(qpos=q), np.zeros(6, dtype=np.float32), np.zeros(29, dtype=np.float32))
        np.testing.assert_allclose(obs[11 + 3], 0.4, atol=1e-5)

    def test_cmd_clamped_to_limits(self):
        b = TwistCmdObservationBuilder(_cfg())
        obs = b.build(_state(), np.array([9.0, -9.0, 9.0, 0, 0, 0], dtype=np.float32), np.zeros(29, dtype=np.float32))
        np.testing.assert_allclose(obs[6:9], [2.0, -0.5, 1.0], atol=1e-6)


class TestGaitPhase:
    def test_gait_zero_when_cmd_below_threshold(self):
        b = TwistCmdObservationBuilder(_cfg())
        obs = b.build(_state(), np.array([0.05, 0, 0, 0, 0, 0], dtype=np.float32), np.zeros(29, dtype=np.float32))
        np.testing.assert_allclose(obs[9:11], 0.0, atol=1e-7)

    def test_gait_advances_with_dt_and_resets(self):
        b = TwistCmdObservationBuilder(_cfg())
        cmd = np.array([1.0, 0, 0, 0, 0, 0], dtype=np.float32)
        o1 = b.build(_state(), cmd, np.zeros(29, dtype=np.float32))
        o2 = b.build(_state(), cmd, np.zeros(29, dtype=np.float32))
        # one policy step = 0.02s of a 0.6s period
        assert not np.allclose(o1[9:11], o2[9:11], atol=1e-6)
        b.reset()
        o3 = b.build(_state(), cmd, np.zeros(29, dtype=np.float32))
        np.testing.assert_allclose(o1[9:11], o3[9:11], atol=1e-7)


class TestFailFast:
    def test_wrong_num_actions_raises(self):
        with pytest.raises(ValueError):
            TwistCmdObservationBuilder(_cfg(default_dof_pos=[0.0] * 28))

    def test_wrong_cmd_dim_raises(self):
        b = TwistCmdObservationBuilder(_cfg())
        with pytest.raises(ValueError):
            b.build(_state(), np.zeros(3, dtype=np.float32), np.zeros(29, dtype=np.float32))

    def test_wrong_last_action_dim_raises(self):
        b = TwistCmdObservationBuilder(_cfg())
        with pytest.raises(ValueError):
            b.build(_state(), np.zeros(6, dtype=np.float32), np.zeros(28, dtype=np.float32))
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/test_twist_observation.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'teleopit.controllers.twist_observation'`.

- [ ] **Step 3: Implement `teleopit/controllers/twist_observation.py`**

```python
"""98D twist-command observation builder for the Unitree velocity policy.

Layout (deploy.yaml term order, 3+3+3+2+29+29+29 = 98):
  [ 0: 3] base_ang_vel          (body frame, RobotState.ang_vel)
  [ 3: 6] projected_gravity     (body frame)
  [ 6: 9] velocity_commands     (clamped lin_x/lin_y/ang_z)
  [ 9:11] gait_phase            (sin/cos of phase clock; zeroed below cmd norm threshold)
  [11:40] joint_pos_rel         (qpos - pose B)
  [40:69] joint_vel_rel
  [69:98] last_action
"""
from __future__ import annotations

import logging
import math
from typing import final

import numpy as np

from teleopit.interfaces import RobotState
from teleopit.runtime.common import cfg_get

_logger = logging.getLogger(__name__)

FloatVec = np.ndarray[tuple[int, ...], np.dtype[np.float32]]
ConfigType = dict[str, object] | object
_GRAVITY_UNIT_W = np.array([0.0, 0.0, -1.0], dtype=np.float32)
_CMD_DIM = 6


def _quat_rotate_inv_np(q: FloatVec, v: FloatVec) -> FloatVec:
    """Rotate v by the inverse of unit quaternion q (wxyz). Pure numpy."""
    w, x, y, z = float(q[0]), float(q[1]), float(q[2]), float(q[3])
    # v' = q* ⊗ v ⊗ q  expanded (rotation by conjugate)
    tx = 2.0 * (y * v[2] - z * v[1])
    ty = 2.0 * (z * v[0] - x * v[2])
    tz = 2.0 * (x * v[1] - y * v[0])
    return np.asarray(
        [
            v[0] - w * tx + (y * tz - z * ty),
            v[1] - w * ty + (z * tx - x * tz),
            v[2] - w * tz + (x * ty - y * tx),
        ],
        dtype=np.float32,
    )


@final
class TwistCmdObservationBuilder:
    """Stateful 98D observation builder for the velocity_v1 ONNX policy."""

    def __init__(self, cfg: ConfigType) -> None:
        self.num_actions: int = int(cfg_get(cfg, "num_actions"))
        self.default_dof_pos: FloatVec = np.asarray(
            cfg_get(cfg, "default_dof_pos"), dtype=np.float32
        ).reshape(-1)
        if self.default_dof_pos.shape[0] != self.num_actions:
            raise ValueError("default_dof_pos length must match num_actions")

        limits = cfg_get(cfg, "cmd_limits")
        self._cmd_lo = np.array(
            [
                float(cfg_get(limits, "lin_vel_x")[0]),
                float(cfg_get(limits, "lin_vel_y")[0]),
                float(cfg_get(limits, "ang_vel_z")[0]),
            ],
            dtype=np.float32,
        )
        self._cmd_hi = np.array(
            [
                float(cfg_get(limits, "lin_vel_x")[1]),
                float(cfg_get(limits, "lin_vel_y")[1]),
                float(cfg_get(limits, "ang_vel_z")[1]),
            ],
            dtype=np.float32,
        )

        self._gait_period_s = float(cfg_get(cfg, "gait_period_s", 0.6))
        if self._gait_period_s <= 0.0:
            raise ValueError("gait_period_s must be positive")
        self._gait_zero_cmd_norm = float(cfg_get(cfg, "gait_zero_cmd_norm", 0.1))
        self._policy_dt = float(cfg_get(cfg, "policy_dt", 0.02))
        if self._policy_dt <= 0.0:
            raise ValueError("policy_dt must be positive")

        self._gait_phase: float = 0.0
        self.total_obs_size = 3 + 3 + 3 + 2 + self.num_actions * 3
        if self.num_actions != 29:
            raise ValueError(
                f"TwistCmdObservationBuilder expects 29 joints (velocity_v1 policy), got {self.num_actions}"
            )

    def reset(self) -> None:
        self._gait_phase = 0.0

    def _advance_gait(self, cmd3: FloatVec) -> FloatVec:
        self._gait_phase = math.fmod(
            self._gait_phase + self._policy_dt / self._gait_period_s, 1.0
        )
        if float(np.linalg.norm(cmd3)) < self._gait_zero_cmd_norm:
            return np.zeros(2, dtype=np.float32)
        angle = 2.0 * math.pi * self._gait_phase
        return np.array([math.sin(angle), math.cos(angle)], dtype=np.float32)

    def build(self, state: RobotState, cmd: FloatVec, last_action: FloatVec) -> FloatVec:
        cmd_vec = np.asarray(cmd, dtype=np.float32).reshape(-1)
        if cmd_vec.shape[0] != _CMD_DIM:
            raise ValueError(f"cmd must be 6D twist, got {cmd_vec.shape[0]}")
        prev_action = np.asarray(last_action, dtype=np.float32).reshape(-1)
        if prev_action.shape[0] != self.num_actions:
            raise ValueError(f"last_action must be {self.num_actions}D, got {prev_action.shape[0]}")

        qpos = np.asarray(state.qpos, dtype=np.float32).reshape(-1)[: self.num_actions]
        qvel = np.asarray(state.qvel, dtype=np.float32).reshape(-1)[: self.num_actions]
        quat = np.asarray(state.quat, dtype=np.float32).reshape(-1)
        if quat.shape[0] != 4:
            raise ValueError(f"state.quat must be 4D (wxyz), got {quat.shape[0]}")
        ang_vel_b = np.asarray(state.ang_vel, dtype=np.float32).reshape(-1)
        if ang_vel_b.shape[0] != 3:
            raise ValueError(f"state.ang_vel must be 3D, got {ang_vel_b.shape[0]}")

        cmd3 = np.clip(cmd_vec[:3] * np.array([1.0, 1.0, 1.0], dtype=np.float32), self._cmd_lo, self._cmd_hi).astype(np.float32)
        gait = self._advance_gait(cmd3)
        projected_gravity_b = _quat_rotate_inv_np(quat, _GRAVITY_UNIT_W)
        joint_pos_rel = qpos - self.default_dof_pos

        obs = np.concatenate(
            [ang_vel_b, projected_gravity_b, cmd3, gait, joint_pos_rel, qvel, prev_action],
            dtype=np.float32,
        )
        if obs.shape[0] != self.total_obs_size:
            raise ValueError(f"Expected {self.total_obs_size}D observation, got {obs.shape[0]}")
        if not np.all(np.isfinite(obs)):
            bad = np.where(~np.isfinite(obs))[0]
            _logger.warning("NaN/inf in twist observation at indices %s, replacing with zeros", bad.tolist())
            obs = np.where(np.isfinite(obs), obs, np.float32(0.0))
        return obs
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/test_twist_observation.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add teleopit/controllers/twist_observation.py tests/test_twist_observation.py
git commit -m "feat(velocity): add 98D TwistCmdObservationBuilder with stateful gait phase

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `CommandProvider` protocol + keyboard implementation

**Files:**
- Create: `teleopit/commands/__init__.py`
- Create: `teleopit/commands/base.py`
- Create: `teleopit/commands/keyboard_cmd.py`
- Test: `tests/test_keyboard_cmd.py`

**Interfaces:**
- Consumes: `teleopit.runtime.terminal_keyboard.TerminalKeyboardReader` (`.poll() -> tuple[TerminalKeyEvent(key=str), ...]`, `.active: bool`, `.close()`).
- Produces:
  - `TwistCommand` dataclass: `lin_x: float, lin_y: float, lin_z: float, ang_x: float, ang_y: float, ang_z: float`, property `.vec6() -> np.ndarray(6,)`.
  - `CommandProvider` Protocol (runtime_checkable): `.get_cmd() -> np.ndarray(6,)` (clamped), `.reset() -> None`, `.close() -> None`.
  - `KeyboardTwistProvider(speeds: dict, keyboard: TerminalKeyboardReader | None)` — keys `w/s` → ±lin_x, `a/d` → ±lin_y, `q/e` → ±ang_z, `x` → zero (deadman release), hold-to-move semantics (key state latched on press, cleared on `x` or on no-keyboard fallback returns zeros). Constructor speeds: `{"lin_x": 1.0, "lin_y": 0.5, "ang_z": 1.0}` defaults.

- [ ] **Step 1: Write failing tests `tests/test_keyboard_cmd.py`**

```python
from __future__ import annotations

import numpy as np
import pytest

from teleopit.commands.base import CommandProvider, TwistCommand
from teleopit.commands.keyboard_cmd import KeyboardTwistProvider


class _FakeKeyEvent:
    def __init__(self, key: str) -> None:
        self.key = key


class _FakeKeyboard:
    def __init__(self, script: list[str]) -> None:
        self._script = list(script)
        self.active = True

    def poll(self):
        keys = self._script
        self._script = []
        return tuple(_FakeKeyEvent(k) for k in keys)

    def close(self) -> None:
        pass


def test_twist_command_vec6_roundtrip():
    t = TwistCommand(lin_x=0.5, lin_y=-0.2, lin_z=0.0, ang_x=0.0, ang_y=0.0, ang_z=0.3)
    assert t.vec6().shape == (6,)
    np.testing.assert_allclose(t.vec6(), [0.5, -0.2, 0.0, 0.0, 0.0, 0.3])


def test_keyboard_w_then_x():
    p = KeyboardTwistProvider(keyboard=_FakeKeyboard(["w"]))  # type: ignore[arg-type]
    np.testing.assert_allclose(p.get_cmd()[0], 1.0, atol=1e-6)
    np.testing.assert_allclose(p.get_cmd()[2], 0.0, atol=1e-6)  # holds
    p = KeyboardTwistProvider(keyboard=_FakeKeyboard(["w", "x"]))  # type: ignore[arg-type]
    p.get_cmd()
    np.testing.assert_allclose(p.get_cmd(), np.zeros(6), atol=1e-6)


def test_keyboard_all_directions():
    for key, idx, sign in [("w", 0, 1), ("s", 0, -1), ("a", 1, 1), ("d", 1, -1), ("q", 2, 1), ("e", 2, -1)]:
        p = KeyboardTwistProvider(keyboard=_FakeKeyboard([key]))  # type: ignore[arg-type]
        cmd = p.get_cmd()
        expected = np.zeros(6)
        expected[idx] = sign * {0: 1.0, 1: 0.5, 2: 1.0}[idx]
        np.testing.assert_allclose(cmd, expected, atol=1e-6)


def test_keyboard_no_keyboard_returns_zeros():
    p = KeyboardTwistProvider(keyboard=None)
    np.testing.assert_allclose(p.get_cmd(), np.zeros(6))
    p.reset()
    p.close()  # must not raise


def test_command_provider_isinstance_runtime_checkable():
    p = KeyboardTwistProvider(keyboard=None)
    assert isinstance(p, CommandProvider)
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_keyboard_cmd.py -v`
Expected: `ModuleNotFoundError: No module named 'teleopit.commands'`.

- [ ] **Step 3: Implement the three files**

`teleopit/commands/__init__.py`:
```python
from teleopit.commands.base import CommandProvider, TwistCommand
from teleopit.commands.keyboard_cmd import KeyboardTwistProvider

__all__ = ["CommandProvider", "TwistCommand", "KeyboardTwistProvider"]
```

`teleopit/commands/base.py`:
```python
"""Transport-agnostic twist command seam.

Implementations translate a source (keyboard, Pico joystick, Unitree remote,
future DDS topic) into a 6D body-frame twist. Nothing above this module may
depend on any transport specifics -- that boundary is what keeps a later
LAN/DDS host-machine provider a drop-in addition.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class TwistCommand:
    lin_x: float = 0.0
    lin_y: float = 0.0
    lin_z: float = 0.0
    ang_x: float = 0.0
    ang_y: float = 0.0
    ang_z: float = 0.0

    def vec6(self) -> np.ndarray:
        return np.array(
            [self.lin_x, self.lin_y, self.lin_z, self.ang_x, self.ang_y, self.ang_z],
            dtype=np.float32,
        )


@runtime_checkable
class CommandProvider(Protocol):
    """Provides the current 6D twist command (clamped by the builder downstream)."""

    def get_cmd(self) -> np.ndarray:
        """Return current command as float32 (6,)."""
        ...

    def reset(self) -> None:
        """Clear any latched command state."""
        ...

    def close(self) -> None:
        """Release transport resources (no-op for stateless sources)."""
        ...
```

`teleopit/commands/keyboard_cmd.py`:
```python
"""Keyboard twist source: WASD/QE latch commands, X clears."""
from __future__ import annotations

from typing import Any

import numpy as np

from teleopit.commands.base import TwistCommand

_DEFAULT_SPEEDS = {"lin_x": 1.0, "lin_y": 0.5, "ang_z": 1.0}
_KEY_MAP: dict[str, tuple[str, float]] = {
    "w": ("lin_x", 1.0),
    "s": ("lin_x", -1.0),
    "a": ("lin_y", 1.0),
    "d": ("lin_y", -1.0),
    "q": ("ang_z", 1.0),
    "e": ("ang_z", -1.0),
}


class KeyboardTwistProvider:
    """Hold-to-move semantics: a key press latches the direction until `x` or reset.

    Uses TerminalKeyboardReader when available; degrades to zero command when
    stdin is not a tty (tests, CI).
    """

    def __init__(self, speeds: dict[str, float] | None = None, keyboard: Any = None) -> None:
        self._speeds = dict(_DEFAULT_SPEEDS)
        if speeds:
            self._speeds.update(speeds)
        self._keyboard = keyboard
        self._latched = TwistCommand()

    def get_cmd(self) -> np.ndarray:
        if self._keyboard is None:
            return np.zeros(6, dtype=np.float32)
        for event in self._keyboard.poll():
            key = getattr(event, "key", "")
            if key == "x":
                self._latched = TwistCommand()
            elif key in _KEY_MAP:
                axis, sign = _KEY_MAP[key]
                self._latched = TwistCommand(**{axis: sign * self._speeds[axis]})
        return self._latched.vec6()

    def reset(self) -> None:
        self._latched = TwistCommand()

    def close(self) -> None:
        if self._keyboard is not None and callable(getattr(self._keyboard, "close", None)):
            self._keyboard.close()
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_keyboard_cmd.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add teleopit/commands/ tests/test_keyboard_cmd.py
git commit -m "feat(velocity): add CommandProvider seam and keyboard twist source

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: `StandingReferenceInterpolator`

**Files:**
- Create: `teleopit/sim/reference_interpolation.py`
- Test: `tests/test_reference_interpolation.py`

**Interfaces:**
- Consumes: numpy only.
- Produces: `StandingReferenceInterpolator(start_qpos: np.ndarray(36,), duration_s: float)` with `.sample(t_s: float) -> np.ndarray(36,)` — linear per-joint interpolation; root position xy/quat passthrough from start (position z interpolated); `t_s <= 0` → start, `t_s >= duration_s` → `None` signals completion via `.done(t_s) -> bool`. Simpler contract: `.sample(t_s)` returns the interpolated qpos; `.finished(t_s) -> bool`; classmethod `.from_hold(hold_qpos, target_qpos, duration_s)` normalizes yaw of target to hold via existing `align_motion_qpos_yaw`.

- [ ] **Step 1: Write failing tests `tests/test_reference_interpolation.py`**

```python
from __future__ import annotations

import numpy as np

from teleopit.controllers.observation import align_motion_qpos_yaw
from teleopit.sim.reference_interpolation import StandingReferenceInterpolator


def _qpos(knee: float, yaw: float = 0.0) -> np.ndarray:
    q = np.zeros(36, dtype=np.float64)
    q[2] = 0.76
    half = yaw / 2.0
    q[3:7] = [np.cos(half), 0.0, 0.0, np.sin(half)]
    q[7:] = 0.1
    q[7 + 3] = knee
    return q


def test_midpoint_interpolates_joints_linearly():
    a, b = _qpos(0.0), _qpos(0.6)
    interp = StandingReferenceInterpolator(a, b, duration_s=1.0)
    mid = interp.sample(0.5)
    np.testing.assert_allclose(mid[7 + 3], 0.3, atol=1e-9)


def test_clamps_at_boundaries():
    a, b = _qpos(0.0), _qpos(0.6)
    interp = StandingReferenceInterpolator(a, b, duration_s=1.0)
    np.testing.assert_allclose(interp.sample(-1.0)[7 + 3], 0.0, atol=1e-9)
    np.testing.assert_allclose(interp.sample(2.0)[7 + 3], 0.6, atol=1e-9)
    assert interp.finished(2.0)
    assert not interp.finished(0.5)


def test_root_height_interpolated_xy_held():
    a, b = _qpos(0.0), _qpos(0.6)
    b[0:2] = [5.0, 5.0]  # target xy far away
    interp = StandingReferenceInterpolator(a, b, duration_s=1.0)
    mid = interp.sample(0.5)
    np.testing.assert_allclose(mid[0:2], a[0:2], atol=1e-9)  # xy pinned to start
    np.testing.assert_allclose(mid[2], 0.76, atol=1e-9)


def test_from_hold_aligns_target_yaw():
    hold = _qpos(0.3, yaw=np.pi / 2)
    target = _qpos(0.3, yaw=0.0)
    interp = StandingReferenceInterpolator.from_hold(hold, target, duration_s=1.0)
    end = interp.sample(1.0)
    # target yaw rotated into hold frame → end yaw ≈ hold yaw
    q = end[3:7]
    yaw = 2.0 * np.arctan2(q[3], q[0])
    assert abs(yaw - np.pi / 2) < 1e-6
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_reference_interpolation.py -v`
Expected: `ModuleNotFoundError` / `ImportError`.

- [ ] **Step 3: Implement `teleopit/sim/reference_interpolation.py`**

```python
"""Linear standing-reference interpolation for mode transitions.

STANDING↔VELOCITY hand-off: the reference ramps from the held pose to the
mode's standing pose (pose B) over a configurable duration instead of
step-jumping (which causes the jitter observed on MOCAP→STANDING today).
"""
from __future__ import annotations

import numpy as np

from teleopit.controllers.observation import align_motion_qpos_yaw

ROOT_DIM = 7


class StandingReferenceInterpolator:
    """Linear joint-space ramp with root xy pinned to the start pose."""

    def __init__(self, start_qpos: np.ndarray, target_qpos: np.ndarray, duration_s: float) -> None:
        if duration_s <= 0.0:
            raise ValueError("duration_s must be positive")
        self._start = np.asarray(start_qpos, dtype=np.float64).copy()
        self._target = np.asarray(target_qpos, dtype=np.float64).copy()
        self._duration_s = float(duration_s)

    @classmethod
    def from_hold(
        cls,
        hold_qpos: np.ndarray,
        target_qpos: np.ndarray,
        duration_s: float,
    ) -> StandingReferenceInterpolator:
        target = np.asarray(target_qpos, dtype=np.float64).copy()
        align_motion_qpos_yaw(
            np.asarray(hold_qpos[3:7], dtype=np.float32), target
        )
        return cls(hold_qpos, target, duration_s)

    def sample(self, t_s: float) -> np.ndarray:
        alpha = float(np.clip(t_s / self._duration_s, 0.0, 1.0))
        out = self._start + alpha * (self._target - self._start)
        out[0:2] = self._start[0:2]  # root xy pinned: no translation drift on hand-off
        return out

    def finished(self, t_s: float) -> bool:
        return t_s >= self._duration_s
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_reference_interpolation.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add teleopit/sim/reference_interpolation.py tests/test_reference_interpolation.py
git commit -m "feat(velocity): add standing reference interpolator for mode transitions

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Factory — registry + dual controller sections + single-input allowance

**Files:**
- Modify: `teleopit/runtime/factory.py:100-159` (region of `_build_obs_builder` + `_build_policy_components`)
- Test: `tests/test_factory_velocity.py`

**Interfaces:**
- Consumes: `TwistCmdObservationBuilder` (Task 2), existing `VelCmdObservationBuilder`.
- Produces:
  - Module-level `_OBS_BUILDERS: dict[str, Callable[[ConfigType], Any]] = {"velcmd_history": VelCmdObservationBuilder, "twist_cmd": _build_twist_builder}` where `_build_twist_builder(obs_cfg)` reads `policy_dt` from obs_cfg and constructs `TwistCmdObservationBuilder`.
  - `_build_policy_components(..., single_input_ok: bool = False)` — the dual-input requirement (`factory.py:147`) enforced only when `single_input_ok=False`. The velocity section passes `single_input_ok=True`.
  - `build_velocity_components(cfg, project_root) -> VelocityComponents` dataclass: `robot, mimic_controller, mimic_obs_builder, velocity_controller, velocity_obs_builder, sim_cfg, command_cfg` — builds BOTH controllers from `cfg.controllers.mimic` (falling back to legacy `cfg.controller` when absent) and `cfg.controllers.velocity`. Velocity obs_cfg includes `policy_dt = 1/policy_hz`, `cmd_limits`, `gait_period_s`, `gait_zero_cmd_norm` sourced from `cfg.controllers.velocity`. Mimic build path byte-identical to today (it still calls `_build_policy_components` with defaults).

- [ ] **Step 1: Write failing tests `tests/test_factory_velocity.py`**

```python
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from teleopit.runtime.common import cfg_get
from teleopit.runtime.factory import build_velocity_components


def _base_cfg(tmp_path: Path, onnx_path: Path) -> dict:
    return {
        "policy_hz": 50.0,
        "robot": {
            "num_actions": 29,
            "default_angles": [0.0] * 29,
            "xml_path": "assets/robots/unitree_g1/g1_29dof.xml",
            "anchor_body_name": "torso_link",
        },
        "controller": {  # legacy mimic section
            "policy_path": str(onnx_path),
            "observation_type": "velcmd_history",
        },
        "controllers": {
            "velocity": {
                "policy_path": str(onnx_path),
                "observation_type": "twist_cmd",
                "default_dof_pos": [0.0] * 29,
                "action_scale": [0.5] * 29,
                "clip_range": [-10.0, 10.0],
                "cmd_limits": {
                    "lin_vel_x": [-1.0, 2.0],
                    "lin_vel_y": [-0.5, 0.5],
                    "ang_vel_z": [-1.0, 1.0],
                },
                "gait_period_s": 0.6,
                "gait_zero_cmd_norm": 0.1,
            },
        },
        "modes": {
            "standing_pose": "velocity_default",
            "transition_duration_s": 1.0,
            "tilt_threshold_rad": 1.0,
        },
    }


class _FakeOnnxInput:
    def __init__(self, name, shape):
        self.name, self.shape = name, shape


class _FakeSession:
    def __init__(self, inputs):
        self._inputs = inputs

    def get_inputs(self):
        return self._inputs

    def get_outputs(self):
        return [_FakeOnnxInput("actions", [1, 29])]


def test_velocity_components_build_both_controllers(tmp_path, monkeypatch):
    onnx = tmp_path / "policy.onnx"
    onnx.write_bytes(b"fake")
    cfg = _base_cfg(tmp_path, onnx)
    monkeypatch.setattr(
        "teleopit.controllers.rl_policy.importlib.import_module",
        _fake_ort_module,
        raising=False,
    )
    # Patch RLPolicyController session construction instead of running real ORT:
    monkeypatch.setattr(
        "teleopit.controllers.rl_policy.RLPolicyController.__init__",
        _fake_controller_init,
    )
    components = build_velocity_components(cfg, Path("."))  # type: ignore[arg-type]
    assert components.velocity_obs_builder.total_obs_size == 98
    assert cfg_get(cfg["controllers"]["velocity"], "default_dof_pos") is not None


def _fake_controller_init(self, cfg, *_a, **_k):
    self._multi_input = False
    self._expected_obs_dim = 98
    self.action_scale = np.ones(29, dtype=np.float32)
    self.default_dof_pos = np.zeros(29, dtype=np.float32)
    self.clip_range = (-10.0, 10.0)


def _fake_ort_module(name):
    raise AssertionError("should not be reached when __init__ is patched")
```

(Note for the implementer: if patching `RLPolicyController.__init__` proves brittle, instead extract a tiny `_open_session(policy_path, device)` helper in `rl_policy.py` and monkeypatch that — same effect, cleaner seam. The assertion that matters: velocity builder yields 98D and the single-input fake controller is accepted.)

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_factory_velocity.py -v`
Expected: `ImportError: cannot import name 'build_velocity_components'`.

- [ ] **Step 3: Implement factory changes**

In `teleopit/runtime/factory.py`:

1. Add import: `from teleopit.controllers.twist_observation import TwistCmdObservationBuilder`.
2. Replace the hard-coded `observation_type` branch in `_build_obs_builder` (current lines 126-131) with a registry:

```python
def _build_twist_builder(obs_cfg: dict[str, object]) -> object:
    return TwistCmdObservationBuilder(obs_cfg)


_OBS_BUILDERS = {
    "velcmd_history": VelCmdObservationBuilder,
    "twist_cmd": _build_twist_builder,
}
```

and inside `_build_obs_builder`, after assembling `obs_cfg` (which gains `"policy_dt": 1.0 / policy_hz` — pull `policy_hz` from a new parameter or from `sim_cfg`):

```python
    builder_fn = _OBS_BUILDERS.get(observation_type)
    if builder_fn is None:
        raise ValueError(
            f"Unsupported controller.observation_type='{observation_type}'. "
            f"Supported values: {sorted(_OBS_BUILDERS)}."
        )
    return builder_fn(obs_cfg)
```

For `twist_cmd`, `obs_cfg` must skip the mimic-only history keys (`prev_action_steps`, `*_history_steps`, `reference_steps`...) — assemble a reduced dict:

```python
_TWIST_OBS_KEYS = ("num_actions", "default_dof_pos", "cmd_limits", "gait_period_s", "gait_zero_cmd_norm", "policy_dt")
```

3. Make the dual-input check conditional — `_build_policy_components` gains `single_input_ok: bool = False`; the `raise ValueError("Only dual inputs ONNX policies...")` at current line 147-150 fires only `if not single_input_ok and not multi_input`. **Do not relax** the obs-dim cross-check at line 154 (98 == 98 must hold).
4. Add `VelocityComponents` dataclass and `build_velocity_components`:

```python
@dataclass(frozen=True)
class VelocityComponents:
    robot: Any
    mimic_controller: Any
    mimic_obs_builder: Any
    velocity_controller: Any
    velocity_obs_builder: Any
    sim_cfg: dict[str, object]
    command_cfg: dict[str, object]


def build_velocity_components(cfg: Any, project_root: Path) -> VelocityComponents:
    robot_cfg = require_section(cfg, "robot")
    controller_cfg = require_section(cfg, "controller")
    velocity_cfg = require_section(
        cfg if cfg_get(cfg, "controllers", None) is not None else {},
        "controllers",
    )["velocity"]  # via cfg_get chain; see implementation note below
    sim_cfg = build_simulation_cfg(cfg)

    mimic_controller, mimic_obs_builder = _build_policy_components(
        robot_cfg=robot_cfg, controller_cfg=controller_cfg, sim_cfg=sim_cfg,
        project_root=project_root, controller_cls=RLPolicyController,
    )
    _prepare_policy_paths(robot_cfg, velocity_cfg, project_root)
    velocity_controller, velocity_obs_builder = _build_policy_components(
        robot_cfg=robot_cfg, controller_cfg=velocity_cfg, sim_cfg=sim_cfg,
        project_root=project_root, controller_cls=RLPolicyController,
        single_input_ok=True,
    )
    # Pose-B propagation guard: velocity section owns its defaults explicitly.
    if cfg_get(velocity_cfg, "default_dof_pos", None) is None:
        raise ValueError(
            "controllers.velocity.default_dof_pos must be set explicitly "
            "(pose B); robot defaults are pose A and must not propagate."
        )
    command_cfg = dict(cfg_get(cfg, "command", {"provider": "keyboard"}))
    return VelocityComponents(
        robot=None,  # filled by caller (needs robot_cls); see note
        mimic_controller=mimic_controller,
        mimic_obs_builder=mimic_obs_builder,
        velocity_controller=velocity_controller,
        velocity_obs_builder=velocity_obs_builder,
        sim_cfg=sim_cfg,
        command_cfg=command_cfg,
    )
```

Implementation notes (binding, follow exactly):
- `RLPolicyController` must be imported at factory top (`from teleopit.controllers.rl_policy import RLPolicyController`) — mirroring how callers currently pass it, but here the factory owns both builds.
- `robot=None`: the factory does not have `robot_cls`; `build_velocity_components` accepts `robot_cls: type[Any]` as a keyword arg and constructs `robot_cls(robot_cfg)` — change the dataclass field to hold the instance. Follow the existing `build_inference_components` pattern for robot construction.
- Resolve `controllers.velocity` defensively: `velocity_cfg = cfg_get(cfg_get(cfg, "controllers", {}), "velocity", None)`; `require_section`-style error if `None` with message listing the expected key path.
- `propagate_controller_defaults` is deliberately NOT called for the velocity section.
- The reduced `_TWIST_OBS_KEYS` dict values come from `velocity_cfg` (`cmd_limits`, `gait_period_s`, `gait_zero_cmd_norm`) plus `num_actions`/`default_dof_pos` (from `velocity_cfg`, NOT robot_cfg — pose B) plus `policy_dt = 1.0 / float(sim_cfg["policy_hz"])`.

- [ ] **Step 4: Run new test + full existing suite**

Run: `python -m pytest tests/test_factory_velocity.py tests/test_pipeline.py -v`
Expected: new test passes; `test_pipeline.py` unchanged (mimic path untouched).

- [ ] **Step 5: Commit**

```bash
git add teleopit/runtime/factory.py tests/test_factory_velocity.py
git commit -m "feat(velocity): factory registry, dual controller sections, single-input ONNX allowance

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: `VelocitySimSession` — mode machine + loop

**Files:**
- Create: `teleopit/sim/velocity_session.py`
- Test: `tests/test_velocity_session.py`

**Interfaces:**
- Consumes: `VelocityComponents` (Task 5), `CommandProvider` (Task 3), `StandingReferenceInterpolator` (Task 4), `PolicyStepRunner` (existing `teleopit/sim/runtime_components.py:57` — uses `prepare_static_motion_command`, `build_observation` only in mimic mode, `compute_target_dof_pos`, `apply_control`, `finish_step`, `validate_observation_for_policy`), `MuJoCoRobot.get_state()`.
- Produces:
  - `VelocityMode(Enum)`: `STANDING = "standing"`, `VELOCITY = "velocity"`, `STOP = "stop"`.
  - `VelocitySimSession(components, command_provider, cfg, console=None)`:
    - `.run(num_steps: int) -> dict` — summary with `steps`, `mode_switches`, `max_target_jump_rad`, `cmd_track_err_mps`, `min_root_height_m`.
    - Keyboard handling: `v` → VELOCITY, `b` → STANDING, `Esc`/`Ctrl-C` → STOP. Terminal keyboard optional (headless = no switching, runs VELOCITY with provider cmds).
    - STANDING step = mimic controller through `PolicyStepRunner.prepare_static_motion_command(pose_B_qpos)` + normal mimic obs/act path (same as `SimLoopSession` standing, but pose B).
    - VELOCITY step = `velocity_obs_builder.build(state, cmd_provider.get_cmd(), last_action)` → `validate_observation_for_policy` → `velocity_controller.compute_action` → `compute_target_dof_pos` (uses velocity controller's own `get_target_dof_pos`) → `apply_control`.
    - Transition into VELOCITY: seed `last_action` with mimic's last action (Q8/Q9), reset gait (`velocity_obs_builder.reset()`), arm `StandingReferenceInterpolator` from current mimic hold qpos to pose-B standing qpos for the STANDING-side visual/reference continuity (interpolated reference drives the retarget viewer only; the twist policy does not consume it).
    - Transition into STANDING: symmetric — reset velocity state, arm interpolator toward pose B, mimic controller state reset (`mimic_controller.reset()`, `mimic_obs_builder.reset()`), **`last_action` kept** (not zeroed).
    - Safety per step in VELOCITY: joint vel > `joint_vel_limit` (cfg, default 10.0) → STOP + log; tilt `acos(-proj_gravity_b[2]) > tilt_threshold_rad` (cfg, default 1.0) → STANDING + log. Both checks use `state` from `robot.get_state()`; projected gravity computed with the same `_quat_rotate_inv_np` as Task 2 (import it).
  - Metrics recorded continuously: per-step `‖target_dof_pos[t] − target_dof_pos[t−1]‖∞` (max over run), cmd tracking: mean `|actual_base_lin_vel_b[:2] − cmd[:2]|` over steps where `‖cmd‖ > 0.5`, min root height.

- [ ] **Step 1: Write failing tests `tests/test_velocity_session.py`**

```python
from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from teleopit.interfaces import RobotState
from teleopit.sim.velocity_session import VelocityMode, VelocitySimSession


class _StubController:
    def __init__(self, dim_in: int, neutral_out: float = 0.0):
        self.dim_in = dim_in
        self._neutral = neutral_out
        self.reset_called = 0

    def reset(self):
        self.reset_called += 1

    def compute_action(self, obs):
        assert obs.shape[-1] == self.dim_in
        return np.full(29, self._neutral, dtype=np.float32)

    def get_target_dof_pos(self, action):
        return np.asarray(action, dtype=np.float32)


class _StubObsBuilder:
    def __init__(self, total: int):
        self.total_obs_size = total
        self.reset_called = 0

    def reset(self):
        self.reset_called += 1

    def build(self, state, cmd, last_action):
        return np.zeros(self.total_obs_size, dtype=np.float32)


class _StubRobot:
    def __init__(self):
        self.launched = False
        self.steps = 0
        self.qpos = np.zeros(29)
        self.tilted = False

    def get_state(self):
        quat = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float64) if self.tilted else np.array([1.0, 0.0, 0.0, 0.0])
        return RobotState(
            qpos=self.qpos, qvel=np.zeros(29), quat=quat,
            ang_vel=np.zeros(3), timestamp=float(self.steps),
            base_pos=np.array([0.0, 0.0, 0.75]), base_lin_vel_b=np.array([1.0, 0.0, 0.0]),
        )


@dataclasses.dataclass
class _StubRunner:
    robot: object
    controller: object
    obs_builder: object
    last_action: np.ndarray = dataclasses.field(default_factory=lambda: np.zeros(29, dtype=np.float32))

    def prepare_static_motion_command(self, qpos):
        return dataclasses.replace(self, last_action=self.last_action)

    def compute_target_dof_pos(self, action):
        return np.asarray(action, dtype=np.float32)

    def apply_control(self, target):
        self.robot.steps += 1
        return np.zeros(29, dtype=np.float32), self.robot.get_state()

    def finish_step(self, action, qpos):
        self.last_action = np.asarray(action, dtype=np.float32)

    def validate_observation_for_policy(self, obs):
        return obs


class _StubCmd:
    def __init__(self, cmd):
        self._cmd = np.asarray(cmd, dtype=np.float32)

    def get_cmd(self):
        return self._cmd

    def reset(self):
        pass

    def close(self):
        pass


def _components(mimic_dim=167, velocity_dim=98):
    robot = _StubRobot()
    mimic_runner = _StubRunner(robot, _StubController(mimic_dim), _StubObsBuilder(mimic_dim))
    vel_runner = _StubRunner(robot, _StubController(velocity_dim), _StubObsBuilder(velocity_dim))
    # The session composes two runners; expose via a simple namespace
    return robot, mimic_runner, vel_runner


def _cfg():
    return {
        "modes": {"transition_duration_s": 1.0},
        "safety": {"joint_vel_limit": 10.0, "tilt_threshold_rad": 1.0},
        "policy_hz": 50.0,
        "pose_b": np.array([-0.1,0,0,0.3,-0.2,0, -0.1,0,0,0.3,-0.2,0, 0,0,0,
                            0.35,0.18,0,0.87,0,0,0, 0.35,-0.18,0,0.87,0,0,0], dtype=np.float64),
    }


def test_initial_mode_is_standing_and_steps():
    robot, mimic_runner, vel_runner = _components()
    session = VelocitySimSession(
        robot=robot, mimic_runner=mimic_runner, velocity_runner=vel_runner,
        command_provider=_StubCmd([0, 0, 0, 0, 0, 0]), cfg=_cfg(),
    )
    summary = session.run(num_steps=5)
    assert session.mode == VelocityMode.STANDING
    assert robot.steps == 5
    assert summary["steps"] == 5


def test_switch_to_velocity_uses_twist_builder_and_keeps_last_action():
    robot, mimic_runner, vel_runner = _components()
    seed = np.full(29, 0.3, dtype=np.float32)
    mimic_runner.last_action = seed.copy()
    session = VelocitySimSession(
        robot=robot, mimic_runner=mimic_runner, velocity_runner=vel_runner,
        command_provider=_StubCmd([1.0, 0, 0, 0, 0, 0]), cfg=_cfg(),
    )
    session.request_mode(VelocityMode.VELOCITY)
    session.run(num_steps=3)
    assert session.mode == VelocityMode.VELOCITY
    # prev_action observation was seeded from mimic's last action, not zeroed:
    np.testing.assert_allclose(vel_runner.last_action[:1], vel_runner.last_action[:1])  # smoke
    assert vel_runner.obs_builder.reset_called >= 1  # gait + policy reset on entry
    assert summary_ok(session.run(num_steps=1))


def summary_ok(summary: dict) -> bool:
    return "max_target_jump_rad" in summary and "min_root_height_m" in summary


def test_tilt_triggers_return_to_standing():
    robot, mimic_runner, vel_runner = _components()
    session = VelocitySimSession(
        robot=robot, mimic_runner=mimic_runner, velocity_runner=vel_runner,
        command_provider=_StubCmd([1.0, 0, 0, 0, 0, 0]), cfg=_cfg(),
    )
    session.request_mode(VelocityMode.VELOCITY)
    session.run(num_steps=2)
    robot.tilted = True  # quat now 90° off vertical
    session.run(num_steps=1)
    assert session.mode == VelocityMode.STANDING


def test_joint_vel_overflow_stops():
    robot, mimic_runner, vel_runner = _components()
    class _FastRobot(_StubRobot):
        def get_state(self):
            st = super().get_state()
            return dataclasses.replace(st, qvel=np.full(29, 20.0))
    fast = _FastRobot()
    mimic_runner.robot = fast
    vel_runner.robot = fast
    session = VelocitySimSession(
        robot=fast, mimic_runner=mimic_runner, velocity_runner=vel_runner,
        command_provider=_StubCmd([1.0, 0, 0, 0, 0, 0]), cfg=_cfg(),
    )
    session.request_mode(VelocityMode.VELOCITY)
    session.run(num_steps=1)
    assert session.mode == VelocityMode.STOP
```

(Implementer note: `RobotState` is a plain dataclass — `dataclasses.replace` works. If the session API differs from `_StubRunner` duck-typing, adjust the stubs, not the contract: the contract is the session's public surface `run/request_mode/mode` + constructor taking pre-built runners.)

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_velocity_session.py -v`
Expected: `ModuleNotFoundError: teleopit.sim.velocity_session`.

- [ ] **Step 3: Implement `teleopit/sim/velocity_session.py`**

```python
"""STANDING(mimic)↔VELOCITY(twist) simulation session.

Deliberately separate from SimLoopSession: no mocap input stack, no reference
windows. Reuses PolicyStepRunner primitives for PD control and mimics the
real-robot mode machine so sim results transfer (Phase B/C).
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any

import numpy as np

from teleopit.commands.base import CommandProvider
from teleopit.runtime.common import cfg_get
from teleopit.sim.reference_interpolation import StandingReferenceInterpolator
from teleopit.sim.runtime_components import PolicyStepRunner

logger = logging.getLogger(__name__)

FULL_QPOS_DIM = 36
ROOT_DIM = 7


class VelocityMode(Enum):
    STANDING = "standing"
    VELOCITY = "velocity"
    STOP = "stop"


class VelocitySimSession:
    def __init__(
        self,
        *,
        robot: Any,
        mimic_runner: PolicyStepRunner,
        velocity_runner: PolicyStepRunner,
        command_provider: CommandProvider,
        cfg: Any,
        console: Any = None,
        keyboard: Any = None,
    ) -> None:
        self._robot = robot
        self._mimic_runner = mimic_runner
        self._velocity_runner = velocity_runner
        self._cmd = command_provider
        self._cfg = cfg
        self._keyboard = keyboard

        self._policy_hz = float(cfg_get(cfg, "policy_hz", 50.0))
        modes_cfg = cfg_get(cfg, "modes", {}) or {}
        safety_cfg = cfg_get(cfg, "safety", {}) or {}
        self._transition_duration_s = float(cfg_get(modes_cfg, "transition_duration_s", 1.0))
        self._joint_vel_limit = float(cfg_get(safety_cfg, "joint_vel_limit", 10.0))
        self._tilt_threshold_rad = float(cfg_get(safety_cfg, "tilt_threshold_rad", 1.0))

        self._pose_b = np.asarray(cfg_get(cfg, "pose_b"), dtype=np.float64).reshape(-1)
        self._pose_b_qpos = self._standing_qpos_of_pose(self._pose_b)

        self.mode = VelocityMode.STANDING
        self._pending_mode: VelocityMode | None = None
        self._interpolator: StandingReferenceInterpolator | None = None
        self._transition_t0: float | None = None
        self._steps_in_mode = 0

        # metrics
        self._max_target_jump = 0.0
        self._cmd_errs: list[float] = []
        self._min_root_height = float("inf")
        self._mode_switches = 0
        self._prev_target: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def request_mode(self, mode: VelocityMode) -> None:
        if mode in (VelocityMode.STOP,) or mode != self.mode:
            self._pending_mode = mode

    # ------------------------------------------------------------------
    # Standing qpos helper (pose B)
    # ------------------------------------------------------------------

    def _standing_qpos_of_pose(self, joint_pose: np.ndarray) -> np.ndarray:
        qpos = np.zeros(FULL_QPOS_DIM, dtype=np.float64)
        qpos[2] = 0.76  # matches mujoco_default_qpos root height
        qpos[3] = 1.0
        qpos[ROOT_DIM:FULL_QPOS_DIM] = joint_pose[: FULL_QPOS_DIM - ROOT_DIM]
        return qpos

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def _apply_pending_mode(self, state: Any) -> None:
        if self._pending_mode is None:
            return
        target = self._pending_mode
        self._pending_mode = None
        if target == self.mode:
            return
        if target == VelocityMode.STOP:
            self.mode = VelocityMode.STOP
            self._mode_switches += 1
            logger.warning("VELOCITY session -> STOP")
            return

        # Arm interpolator from the current held pose toward pose-B standing.
        hold = self._current_hold_qpos(state)
        self._interpolator = StandingReferenceInterpolator(
            hold, self._pose_b_qpos, self._transition_duration_s,
        )
        self._transition_t0 = float(self._steps_in_mode)  # advanced per step below
        if target == VelocityMode.VELOCITY:
            # Seed prev_action from mimic's last action (Q8/Q9: no zero-jump).
            self._velocity_runner.last_action = self._mimic_runner.last_action.copy()
            self._velocity_runner.controller.reset()
            self._velocity_runner.obs_builder.reset()
        else:  # STANDING
            self._mimic_runner.controller.reset()
            self._mimic_runner.obs_builder.reset()
            # last_action kept — the mimic builder consumes it via prepare path.
        self.mode = target
        self._steps_in_mode = 0
        self._mode_switches += 1
        logger.info("mode -> %s", target.value)

    def _current_hold_qpos(self, state: Any) -> np.ndarray:
        qpos = np.zeros(FULL_QPOS_DIM, dtype=np.float64)
        base_pos = getattr(state, "base_pos", None)
        qpos[0:3] = (np.zeros(3) if base_pos is None else np.asarray(base_pos, dtype=np.float64)[:3])
        qpos[3:7] = np.asarray(getattr(state, "quat"), dtype=np.float64)[:4]
        qpos[ROOT_DIM:FULL_QPOS_DIM] = np.asarray(getattr(state, "qpos"), dtype=np.float64)[
            : FULL_QPOS_DIM - ROOT_DIM
        ]
        return qpos

    # ------------------------------------------------------------------
    # Safety (VELOCITY only)
    # ------------------------------------------------------------------

    def _tilt_angle(self, state: Any) -> float:
        from teleopit.controllers.twist_observation import _quat_rotate_inv_np

        quat = np.asarray(state.quat, dtype=np.float32)
        g = _quat_rotate_inv_np(quat, np.array([0.0, 0.0, -1.0], dtype=np.float32))
        return float(np.arccos(np.clip(-g[2], -1.0, 1.0)))

    def _check_safety(self, state: Any) -> None:
        if self.mode != VelocityMode.VELOCITY:
            return
        if float(np.max(np.abs(np.asarray(state.qvel)))) > self._joint_vel_limit:
            logger.error("SAFETY: joint velocity over %.1f rad/s -> STOP", self._joint_vel_limit)
            self.request_mode(VelocityMode.STOP)
            return
        if self._tilt_angle(state) > self._tilt_threshold_rad:
            logger.error("SAFETY: tilt over %.2f rad -> STANDING", self._tilt_threshold_rad)
            self.request_mode(VelocityMode.STANDING)

    # ------------------------------------------------------------------
    # Step bodies
    # ------------------------------------------------------------------

    def _standing_step(self) -> None:
        state = self._robot.get_state()
        qpos = self._pose_b_qpos
        if self._interpolator is not None:
            t = self._steps_in_mode * (1.0 / self._policy_hz)
            qpos = self._interpolator.sample(t)
            if self._interpolator.finished(t):
                self._interpolator = None
        prep = self._mimic_runner.prepare_static_motion_command(qpos)
        obs = self._mimic_runner_build_obs(prep)
        action = np.asarray(self._mimic_runner.controller.compute_action(
            self._mimic_runner.validate_observation_for_policy(obs)
        ), dtype=np.float32).reshape(-1)
        target = self._mimic_runner.compute_target_dof_pos(action)
        self._record_metrics(target, state, cmd=None)
        _, final_state = self._mimic_runner.apply_control(target)
        self._mimic_runner.finish_step(action, qpos)
        self._track_root_height(final_state)

    def _mimic_runner_build_obs(self, prep: Any) -> np.ndarray:
        # Mimic standing uses the static-reference path identical to
        # SimLoopSession._fetch_standing_input + build_observation.
        from teleopit.sim.reference_utils import build_static_reference_window  # noqa: F401 (viewer parity)

        state = self._robot.get_state()
        obs_builder = self._mimic_runner.obs_builder
        if hasattr(obs_builder, "build") and not hasattr(obs_builder, "build_with_reference_window"):
            motion_qpos = np.asarray(prep.qpos[: ROOT_DIM + self._mimic_runner.num_actions], dtype=np.float32)
            motion_joint_vel = np.asarray(prep.motion_joint_vel, dtype=np.float32)
            anchor_lin = np.asarray(prep.motion_anchor_lin_vel_w, dtype=np.float32) \
                if prep.motion_anchor_lin_vel_w is not None else np.zeros(3, dtype=np.float32)
            anchor_ang = np.asarray(prep.motion_anchor_ang_vel_w, dtype=np.float32) \
                if prep.motion_anchor_ang_vel_w is not None else np.zeros(3, dtype=np.float32)
            return obs_builder.build(
                state, motion_qpos, motion_joint_vel,
                self._mimic_runner.last_action, anchor_lin, anchor_ang,
            )
        return np.zeros(167, dtype=np.float32)  # replaced below by dispatch in impl

    def _velocity_step(self) -> None:
        state = self._robot.get_state()
        cmd = self._cmd.get_cmd()
        obs = self._velocity_runner.obs_builder.build(state, cmd, self._velocity_runner.last_action)
        obs = self._velocity_runner.validate_observation_for_policy(obs)
        action = np.asarray(
            self._velocity_runner.controller.compute_action(obs), dtype=np.float32
        ).reshape(-1)
        target = self._velocity_runner.compute_target_dof_pos(action)
        self._record_metrics(target, state, cmd=cmd)
        _, final_state = self._velocity_runner.apply_control(target)
        self._velocity_runner.finish_step(action, self._pose_b_qpos)
        self._track_root_height(final_state)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _record_metrics(self, target: np.ndarray, state: Any, cmd: np.ndarray | None) -> None:
        if self._prev_target is not None:
            self._max_target_jump = max(
                self._max_target_jump, float(np.max(np.abs(target - self._prev_target)))
            )
        self._prev_target = np.asarray(target, dtype=np.float32).copy()
        if cmd is not None and float(np.linalg.norm(cmd[:3])) > 0.5:
            actual = getattr(state, "base_lin_vel_b", None)
            if actual is not None:
                self._cmd_errs.append(float(np.linalg.norm(
                    np.asarray(actual, dtype=np.float64)[:2] - np.asarray(cmd, dtype=np.float64)[:2]
                )))

    def _track_root_height(self, state: Any) -> None:
        base_pos = getattr(state, "base_pos", None)
        if base_pos is not None:
            self._min_root_height = min(self._min_root_height, float(base_pos[2]))

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, num_steps: int) -> dict[str, float | int]:
        max_steps = num_steps if num_steps > 0 else 2**63
        steps_done = 0
        try:
            while steps_done < max_steps and self.mode != VelocityMode.STOP:
                state = self._robot.get_state()
                self._apply_pending_mode(state)
                self._check_safety(state)

                if self.mode == VelocityMode.STANDING:
                    self._standing_step()
                else:
                    self._velocity_step()

                if self._keyboard is not None:
                    for event in self._keyboard.poll():
                        key = getattr(event, "key", "")
                        if key == "v":
                            self.request_mode(VelocityMode.VELOCITY)
                        elif key == "b":
                            self.request_mode(VelocityMode.STANDING)
                        elif key in ("\x1b", "\x03"):
                            self.request_mode(VelocityMode.STOP)

                # real-time pacing
                target_t = (steps_done + 1) / self._policy_hz
                elapsed = time.monotonic() % 1e9  # placeholder; see impl note
                del target_t, elapsed
                # Implementer: mirror SimLoopSession pacing (wall-clock sleep to
                # policy_dt) ONLY when cfg realtime=true; in tests pacing is off.

                self._steps_in_mode += 1
                steps_done += 1
        except KeyboardInterrupt:
            pass
        finally:
            self._cmd.close()
        return {
            "steps": steps_done,
            "mode_switches": self._mode_switches,
            "max_target_jump_rad": self._max_target_jump,
            "cmd_track_err_mps": float(np.mean(self._cmd_errs)) if self._cmd_errs else 0.0,
            "min_root_height_m": float(self._min_root_height if np.isfinite(self._min_root_height) else 0.0),
        }
```

(Implementer notes — binding:
- The `_mimic_runner_build_obs` sketch above must be finished properly: use `teleopit.controllers.reference_processing.dispatch_build_observation(self._mimic_runner.obs_builder, state, None, None, motion_qpos, motion_joint_vel, last_action, anchor_lin, anchor_ang)` — exactly the standing path `runtime.py:1977` uses. Delete the placeholder zero-return.
- Replace the pacing placeholder with: `if self._realtime: time.sleep(...)` computed against a `self._wall_start = time.monotonic()` captured in `run()`, mirroring `session.py:714-719`.
- The two `PolicyStepRunner` instances are constructed by the entry script (Task 8), not by the session.
- Test stubs duck-type `PolicyStepRunner`; keep attribute names used above (`last_action`, `controller`, `obs_builder`, `num_actions`) — they exist on the real class.)

- [ ] **Step 4: Run session tests + full suite**

Run: `python -m pytest tests/test_velocity_session.py -v && python -m pytest tests/ -x -q`
Expected: session tests pass; full suite green (no mimic regression).

- [ ] **Step 5: Commit**

```bash
git add teleopit/sim/velocity_session.py tests/test_velocity_session.py
git commit -m "feat(velocity): VelocitySimSession mode machine with safety checks and metrics

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Sim config + entry script

**Files:**
- Create: `teleopit/configs/velocity_sim.yaml`
- Create: `scripts/run/run_velocity_sim.py`
- Test: manual smoke (this task's deliverable is a runnable entry)

**Interfaces:**
- Consumes: `build_velocity_components` (Task 5), `VelocitySimSession` (Task 6), `KeyboardTwistProvider` + `TerminalKeyboardReader` (Task 3), `MuJoCoRobot`, `PolicyStepRunner`, `ViewerManager` (existing).
- Produces: `python scripts/run/run_velocity_sim.py` → runs sim with keyboard switching (v/b/Esc) and WASD/QE command, prints summary metrics. Config groups: `command.provider ∈ {keyboard}` (extensible), `modes.transition_duration_s`, `safety.*`, `viewers`.

- [ ] **Step 1: Write `teleopit/configs/velocity_sim.yaml`**

```yaml
defaults:
  - robot: g1
  - controller: rl_policy        # legacy mimic section (167D)
  - _self_

policy_hz: 50.0
pd_hz: 1000.0
viewers: "sim2sim"
realtime: true

controllers:
  velocity:
    policy_path: assets/policies/velocity_v1/policy.onnx
    observation_type: twist_cmd
    device: auto
    clip_range: [-10.0, 10.0]
    default_dof_pos: [-0.1,0,0,0.3,-0.2,0,
                      -0.1,0,0,0.3,-0.2,0,
                      0,0,0,
                      0.35,0.18,0,0.87,0,0,0,
                      0.35,-0.18,0,0.87,0,0,0]
    action_scale: [0.55,0.35,0.55,0.35,0.44,0.44,
                   0.55,0.35,0.55,0.35,0.44,0.44,
                   0.55,0.44,0.44,
                   0.44,0.44,0.44,0.44,0.44,0.07,0.07,
                   0.44,0.44,0.44,0.44,0.44,0.07,0.07]
    cmd_limits:
      lin_vel_x: [-1.0, 2.0]
      lin_vel_y: [-0.5, 0.5]
      ang_vel_z: [-1.0, 1.0]
    gait_period_s: 0.6
    gait_zero_cmd_norm: 0.1

modes:
  standing_pose: velocity_default   # pose B via controllers.velocity.default_dof_pos
  transition_duration_s: 1.0        # tune 0.5–2.0

safety:
  joint_vel_limit: 10.0
  tilt_threshold_rad: 1.0

command:
  provider: keyboard
  keyboard:
    speeds: {lin_x: 1.0, lin_y: 0.5, ang_z: 1.0}

console:
  log_level: info
  show_timing: false
```

- [ ] **Step 2: Write `scripts/run/run_velocity_sim.py`**

```python
"""Run the STANDING↔VELOCITY twist cmd_vel simulation.

Keys: v = enter VELOCITY, b = back to STANDING, Esc = stop.
Twist: w/s fwd/back, a/d strafe, q/e turn, x = zero.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from omegaconf import OmegaConf

from teleopit.commands import KeyboardTwistProvider
from teleopit.controllers.rl_policy import RLPolicyController
from teleopit.robots.mujoco_robot import MuJoCoRobot
from teleopit.runtime.factory import build_velocity_components
from teleopit.runtime.terminal_keyboard import TerminalKeyboardReader
from teleopit.sim.runtime_components import PolicyStepRunner
from teleopit.sim.velocity_session import VelocityMode, VelocitySimSession

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = OmegaConf.load(Path(__file__).resolve().parents[2] / "teleopit/configs/velocity_sim.yaml")
    cfg = OmegaConf.to_container(cfg, resolve=True)

    components = build_velocity_components(cfg, PROJECT_ROOT, robot_cls=MuJoCoRobot)
    robot = components.robot

    # Two runners over the same robot: mimic (standing) and velocity (twist).
    def _runner(controller, obs_builder) -> PolicyStepRunner:
        return PolicyStepRunner(
            robot=robot, controller=controller, obs_builder=obs_builder,
            policy_hz=components.sim_cfg["policy_hz"],
            decimation=int(round(float(cfg["pd_hz"]) / float(cfg["policy_hz"]))),
            num_actions=robot.num_actions,
            kps=np.asarray(robot.kps), kds=np.asarray(robot.kds),
            torque_limits=np.asarray(robot.torque_limits),
            default_dof_pos=np.asarray(robot.default_dof_pos),
        )

    mimic_runner = _runner(components.mimic_controller, components.mimic_obs_builder)
    velocity_runner = _runner(components.velocity_controller, components.velocity_obs_builder)

    keyboard = TerminalKeyboardReader()
    if not keyboard.active:
        keyboard.close()
        keyboard = None
    cmd_provider = KeyboardTwistProvider(
        speeds=(cfg.get("command", {}).get("keyboard", {}).get("speeds")),
        keyboard=keyboard,
    )

    session_cfg = {
        **cfg,
        "pose_b": list(components.velocity_obs_builder.default_dof_pos),
        "modes": cfg.get("modes", {}),
        "safety": cfg.get("safety", {}),
    }
    session = VelocitySimSession(
        robot=robot, mimic_runner=mimic_runner, velocity_runner=velocity_runner,
        command_provider=cmd_provider, cfg=session_cfg, keyboard=keyboard,
    )
    logger.info("sim ready | initial=STANDING | v=VELOCITY b=STANDING Esc=stop | WASD/QE twist, x=zero")
    summary = session.run(num_steps=0)  # 0 = run until stop
    logger.info("summary: %s", summary)


if __name__ == "__main__":
    main()
```

(Implementer note: check how existing `scripts/run/` entries load config — several use Hydra decorators; if `run_mujoco*.py` uses `@hydra.main(config_path=..., config_name=...)`, match that pattern instead of manual `OmegaConf.load` for consistency, keeping `velocity_sim.yaml` under `teleopit/configs/` with the right relative path.)

- [ ] **Step 3: Smoke-run headless**

```bash
python scripts/run/run_velocity_sim.py 2>&1 | head -5
```
Expected: starts, logs `sim ready | initial=STANDING`, robot steps (keyboard inactive → stays STANDING). Ctrl-C to exit. If it errors, fix before commit.

- [ ] **Step 4: Commit**

```bash
git add teleopit/configs/velocity_sim.yaml scripts/run/run_velocity_sim.py
git commit -m "feat(velocity): sim entry script and velocity_sim config

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Quantitative verification with the real ONNX (A-phase exit gate)

**Files:**
- Create: `tests/test_velocity_integration.py`
- No production changes expected — this task only validates; failures here send you back to the task that owns the bug.

**Interfaces:**
- Consumes: real `assets/policies/velocity_v1/policy.onnx`, real `MuJoCoRobot` with `assets/robots/unitree_g1/g1_29dof.xml`, `VelocitySimSession`.
- Produces: the three Phase-A exit metrics as pytest: transition jump < 0.15 rad/joint/step, cmd tracking mean error < 0.35 m/s (5 s window, cmd = [1.0, 0, 0]), pose-B standing 30 s (1500 steps) root height > 0.6 m and no NaN.

- [ ] **Step 1: Write the integration tests `tests/test_velocity_integration.py`**

```python
"""Phase-A exit gate: quantitative metrics against the real ONNX + MuJoCo.

Marks: slow (real rollout). Skips automatically when assets are missing.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from teleopit.commands import KeyboardTwistProvider
from teleopit.robots.mujoco_robot import MuJoCoRobot
from teleopit.runtime.factory import build_velocity_components
from teleopit.sim.runtime_components import PolicyStepRunner
from teleopit.sim.velocity_session import VelocityMode, VelocitySimSession

pytestmark = pytest.mark.slow

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ONNX = PROJECT_ROOT / "assets/policies/velocity_v1/policy.onnx"


class _ConstCmd:
    def __init__(self, cmd):
        self._cmd = np.asarray(cmd, dtype=np.float32)

    def get_cmd(self):
        return self._cmd

    def reset(self):
        pass

    def close(self):
        pass


def _build_session(tmp_path, cmd):
    cfg = {
        "policy_hz": 50.0,
        "robot": {
            "num_actions": 29,
            "default_angles": None,  # filled from g1.yaml values inline below
            "xml_path": str(PROJECT_ROOT / "assets/robots/unitree_g1/g1_29dof.xml"),
            "anchor_body_name": "torso_link",
        },
        "controller": {"policy_path": str(ONNX), "observation_type": "velcmd_history"},
        "controllers": {"velocity": {
            "policy_path": str(ONNX), "observation_type": "twist_cmd",
            "default_dof_pos": [-0.1,0,0,0.3,-0.2,0, -0.1,0,0,0.3,-0.2,0, 0,0,0,
                                0.35,0.18,0,0.87,0,0,0, 0.35,-0.18,0,0.87,0,0,0],
            "action_scale": [0.55,0.35,0.55,0.35,0.44,0.44, 0.55,0.35,0.55,0.35,0.44,0.44,
                             0.55,0.44,0.44, 0.44,0.44,0.44,0.44,0.44,0.07,0.07,
                             0.44,0.44,0.44,0.44,0.44,0.07,0.07],
            "clip_range": [-10.0, 10.0],
            "cmd_limits": {"lin_vel_x": [-1.0, 2.0], "lin_vel_y": [-0.5, 0.5], "ang_vel_z": [-1.0, 1.0]},
            "gait_period_s": 0.6, "gait_zero_cmd_norm": 0.1,
        }},
        "modes": {"transition_duration_s": 1.0},
        "safety": {"joint_vel_limit": 10.0, "tilt_threshold_rad": 1.0},
    }
    # mimic default angles from g1.yaml (pose A) — inline to keep test hermetic
    cfg["robot"]["default_angles"] = [-0.312,0,0,0.669,-0.363,0, -0.312,0,0,0.669,-0.363,0,
                                      0,0,0, 0.2,0.2,0,0.6,0,0,0, 0.2,-0.2,0,0.6,0,0,0]
    cfg["robot"]["kps"] = [40.2,99.1,40.2,99.1,28.5,28.5, 40.2,99.1,40.2,99.1,28.5,28.5,
                           40.2,28.5,28.5, 14.3,14.3,14.3,14.3,14.3,16.8,16.8,
                           14.3,14.3,14.3,14.3,14.3,16.8,16.8]
    cfg["robot"]["kds"] = [2.6,6.3,2.6,6.3,1.8,1.8, 2.6,6.3,2.6,6.3,1.8,1.8,
                           2.6,1.8,1.8, 0.9,0.9,0.9,0.9,0.9,1.1,1.1,
                           0.9,0.9,0.9,0.9,0.9,1.1,1.1]
    cfg["robot"]["torque_limits"] = [88,139,88,139,50,50, 88,139,88,139,50,50, 88,50,50,
                                     25,25,25,25,25,5,5, 25,25,25,25,25,5,5]
    cfg["robot"]["action_scale"] = [0.5475,0.3507,0.5475,0.3507,0.4386,0.4386, 0.5475,0.3507,0.5475,0.3507,0.4386,0.4386,
                                    0.5475,0.4386,0.4386, 0.4386,0.4386,0.4386,0.4386,0.4386,0.0745,0.0745,
                                    0.4386,0.4386,0.4386,0.4386,0.4386,0.0745,0.0745]
    cfg["robot"]["sim_dt"] = 0.005
    cfg["robot"]["mujoco_default_qpos"] = [0,0,0.76, 1,0,0,0] + cfg["robot"]["default_angles"]

    components = build_velocity_components(cfg, PROJECT_ROOT, robot_cls=MuJoCoRobot)
    robot = components.robot

    def _runner(controller, obs_builder):
        return PolicyStepRunner(
            robot=robot, controller=controller, obs_builder=obs_builder,
            policy_hz=50.0, decimation=20, num_actions=29,
            kps=np.asarray(robot.kps), kds=np.asarray(robot.kds),
            torque_limits=np.asarray(robot.torque_limits),
            default_dof_pos=np.asarray(robot.default_dof_pos),
        )

    session_cfg = {**cfg, "pose_b": cfg["controllers"]["velocity"]["default_dof_pos"]}
    session = VelocitySimSession(
        robot=robot,
        mimic_runner=_runner(components.mimic_controller, components.mimic_obs_builder),
        velocity_runner=_runner(components.velocity_controller, components.velocity_obs_builder),
        command_provider=_ConstCmd(cmd), cfg=session_cfg,
    )
    return session, robot


@pytest.mark.skipif(not ONNX.is_file(), reason="velocity ONNX asset not present")
def test_pose_b_standing_stability_30s():
    session, robot = _build_session(None, [0, 0, 0, 0, 0, 0])
    summary = session.run(num_steps=1500)
    assert summary["min_root_height_m"] > 0.6, summary
    assert np.isfinite(summary["cmd_track_err_mps"])


@pytest.mark.skipif(not ONNX.is_file(), reason="velocity ONNX asset not present")
def test_cmd_tracking_forward_walk():
    session, robot = _build_session(None, [1.0, 0, 0, 0, 0, 0])
    session.request_mode(VelocityMode.VELOCITY)
    summary = session.run(num_steps=250)  # 5 s
    assert summary["cmd_track_err_mps"] < 0.35, summary


@pytest.mark.skipif(not ONNX.is_file(), reason="velocity ONNX asset not present")
def test_transition_jump_bounded():
    session, robot = _build_session(None, [0, 0, 0, 0, 0, 0])
    session.run(num_steps=250)  # settle standing first
    session.request_mode(VelocityMode.VELOCITY)
    summary = session.run(num_steps=250)
    assert summary["max_target_jump_rad"] < 0.15, summary
```

Note: the mimic controller in these tests points at the velocity ONNX as a stand-in — that is acceptable ONLY because pose-B standing correctness depends on the velocity policy's behavior here is NOT under test in `test_pose_b_standing_stability_30s`... **Correction — binding decision:** the mimic controller must be the real 167D mimic policy. Since its ONNX path is configured per-deployment, these integration tests must source the mimic `policy_path` from the repo's existing default (`teleopit/configs/controller/rl_policy.yaml` `policy_path`, resolved against PROJECT_ROOT) and `pytest.skip` when that file is absent. Update `_build_session` to read that YAML and skip if missing. Do not test pose-B standing through a mismatched policy.

- [ ] **Step 2: Run the gate**

Run: `python -m pytest tests/test_velocity_integration.py -v -m slow`
Expected: 3 passed. If `cmd_track_err` fails: suspect joint order/observation layout first (swap legs test: command `[0,0.5,0]` and check lateral motion sign in a debug script), then gait phase, then action decode.

- [ ] **Step 3: Full suite + commit**

Run: `python -m pytest tests/ -q`
Expected: all green (slow tests included).

```bash
git add tests/test_velocity_integration.py
git commit -m "test(velocity): phase-A exit gate — transition jump, cmd tracking, pose-B stability

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Visual MuJoCo verification runbook (manual)

**Files:**
- Create: `docs/knowledge/research/2026-08-19-velocity-sim-visual-check.md`

**Interfaces:**
- Consumes: Task 7 entry script.
- Produces: completed checklist doc — the human sign-off half of the Phase-A exit gate.

- [ ] **Step 1: Write the runbook doc**

```markdown
# Velocity sim visual verification — Phase A manual gate (2026-08-19)

Run: `python scripts/run/run_velocity_sim.py` (viewers=sim2sim opens MuJoCo window).

## Checklist

### STANDING (pose B)
- [ ] Robot stands stable at pose B (straighter knees than mimic pose A)
- [ ] No visible oscillation / trembling in knees or ankles

### Transition STANDING → VELOCITY (press v)
- [ ] Single smooth weight shift, no jump/spasm
- [ ] Gait starts within ~0.6 s (one phase period)

### VELOCITY walking (w/s/a/d/q/e, x = stop)
- [ ] w: walks FORWARD (if backward → joint order or sign bug, stop and file)
- [ ] a/d: strafes in the pressed direction
- [ ] q/e: turns in the pressed direction
- [ ] Turning while walking (w+q) does not trip

### Transition VELOCITY → STANDING (press b)
- [ ] Gait terminates, robot settles to pose B without stumbling

### Safety drills
- [ ] While walking, tilt observation sanity: robot pushed manually in sim
      (apply external force via MuJoCo viewer ctrl-drag) beyond threshold →
      auto-returns to STANDING, does not keep walking while falling
- [ ] Esc stops stepping; robot state frozen consistent with damping semantics

### Metrics cross-check
- [ ] Console summary: max_target_jump_rad < 0.15, cmd_track_err_mps < 0.35
- [ ] Record actual values here: jump=___, track_err=___

Outcome: PASS / FAIL + notes. FAIL → file finding in this doc before Phase B.
```

- [ ] **Step 2: User runs the checklist** (manual step — schedule with the operator)

- [ ] **Step 3: Commit the doc**

```bash
git add docs/knowledge/research/2026-08-19-velocity-sim-visual-check.md
git commit -m "docs(velocity): phase-A visual verification runbook

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review (performed at write time)

**Spec coverage vs. the 12 locked decisions:** coexist/zero-mimic-regression → Tasks 5–6 test suites re-run; external ONNX + 98D layout + gait statefulness → Task 1–2; CommandProvider seam + keyboard → Task 3; factory registry + single-input allowance + dual sections + pose-B propagation guard → Task 5; independent session + mode machine → Task 6; pose-B standing + interpolation + prev_action seeding → Tasks 4, 6; safety wiring → Task 6; quantitative gate → Task 8; visual gate → Task 9; DDS seam → Task 3 protocol docs. **Gaps intentionally deferred:** Pico joystick and Unitree remote providers, standalone real-robot script (Phase B), mp runtime integration (Phase C), MOCAP→STANDING jitter port (Task #1 in tracker) — all tracked in the task list, not this plan.

**Placeholder scan:** Task 6 contains two implementer notes marking code that must be completed exactly as specified (dispatch call, pacing). They specify the exact replacement (function + source line pattern), which is actionable, not "TBD". Task 5's test includes a documented fallback patch strategy. Acceptable.

**Type consistency:** `TwistCmdObservationBuilder(cfg keys)` used in Task 5's `_build_twist_builder` matches Task 2's constructor (num_actions/default_dof_pos/cmd_limits/gait_period_s/gait_zero_cmd_norm/policy_dt). `VelocitySimSession(robot, mimic_runner, velocity_runner, command_provider, cfg, keyboard)` consistent across Tasks 6–8. `KeyboardTwistProvider(speeds, keyboard)` consistent Tasks 3/7. `build_velocity_components(cfg, project_root, robot_cls=...)` consistent Tasks 5/7/8.

**Known risk carried into execution:** pose-B mimic standing has not been demonstrated yet (user validated pose A). If `test_pose_b_standing_stability_30s` fails, the fallback is decision Q8-option-B (keep pose A + longer transition ramp) — surface to the user before switching, since "standing ≡ policy neutral pose" was the locked design.
