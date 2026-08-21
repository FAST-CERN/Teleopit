# Pico Sim VELOCITY Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add VELOCITY as the 4th `SimulationMode` of the sim pico teleop state machine (`SimLoopSession`), driven by the Pico joystick (or keyboard fallback), producing a runnable pico sim teleop environment + launch command.

**Architecture:** The Phase A twist channel's proven machinery (joint-space prev_action seeding, step core, safety, metrics) is extracted from `VelocitySimSession` into a shared `VelocityStepController`; `SimLoopSession` gains a `VELOCITY` mode branch that runs the twist policy step instead of the mimic step while the pico skeleton stream keeps flowing. A new `PicoJoystickProvider` (CommandProvider) maps controller sticks to a 6D twist; provider auto-selected by input source. V enters VELOCITY only from STANDING; X returns to STANDING through a yaw-preserving reference ramp. `VelocitySimSession` + `run_velocity_sim.py` keep working unchanged in behavior (dual entry).

**Tech Stack:** Python 3.10 (conda env `teleopit`), NumPy, MuJoCo, ONNX Runtime, Hydra/OmegaConf, pytest.

## Global Constraints

- Python is ALWAYS `C:/Users/user/.conda/envs/teleopit/python.exe` (never bare `python`). Run pytest from the checkout root: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/<file> -v`. The repo is pip-installed, so no PYTHONPATH is needed from the root.
- Work in a git worktree on branch `worktree-pico-velocity-sim` (created at execution time via superpowers:using-git-worktrees); merge to `master` only after all gates pass. cwd for every command = the worktree root.
- pd_hz 200 / policy_hz 50 / robot sim_dt 0.005 invariant: `decimation * sim_dt == 1/policy_hz`. Never change `pd_hz` or `policy_hz` in any config this plan touches.
- Mocap path behavior: ZERO changes to MOCAP-mode stepping, retargeting, reference windows, pause/resume, and the ARMS mode. The VELOCITY branch is additive; when `simulation_mode != VELOCITY`, `SimLoopSession.run()` executes the exact code path it does today.
- Unity bridge needs NO changes (it already sends `axisX`/`axisY` per controller; verified `PicoTrackingCollector.cs:117-128` and pico_bridge `frames.py:281-286` parses them into `ControllerState.axis["x"]/["y"]`). All fixes are Python-side.
- cmd limits from `teleopit/configs/controller/velocity.yaml`: lin_x [-1.0, 2.0], lin_y [-0.5, 0.5], ang_z [-1.0, 1.0]. Joystick deadzone 0.15.
- No new runtime dependencies.
- Commit style: conventional commits (`feat:`, `refactor:`, `test:`, `docs:`), one commit per task's green state.

## File Structure

- **Create** `teleopit/commands/pico_joystick.py` — `PicoJoystickProvider` (CommandProvider): reads `PicoControllerSnapshot` from `Pico4InputProvider.get_controller_snapshot()`, applies deadzone + linear map to cmd limits, zeros on stale/disconnected data.
- **Create** `teleopit/sim/velocity_step.py` — `VelocityStepController`: the extracted step core (joint-space prev_action seed, velocity step body, standing step body helpers, safety checks) shared by `VelocitySimSession` and `SimLoopSession`.
- **Create** `teleopit/configs/pico4_sim_velocity.yaml` — pico teleop config with velocity sections (the launch config).
- **Create** `tests/test_pico_joystick_cmd.py`, `tests/test_velocity_step.py`.
- **Modify** `teleopit/commands/__init__.py` — export `PicoJoystickProvider`.
- **Modify** `teleopit/inputs/pico4_provider.py` — expose `axis_x`/`axis_y` on `PicoControllerState`.
- **Modify** `teleopit/sim/velocity_session.py` — delegate extracted internals to `VelocityStepController`; public behavior unchanged.
- **Modify** `teleopit/sim/loop.py` — `SimulationMode.VELOCITY`; `attach_velocity_stack`.
- **Modify** `teleopit/sim/session.py` — `enter_velocity_mode` / `exit_velocity_to_standing`, V/X routing, VELOCITY branch in `run()`, skeleton keeps flowing.
- **Modify** `teleopit/pipeline.py` — detect `controllers.velocity`, build + attach the velocity stack, select command provider.
- **Modify** `teleopit/runtime/factory.py` — public wrapper for building the velocity policy pair.
- **Modify** `teleopit/runtime/console.py` — `sim_keyboard_controls` gains V entry.
- **Modify** `scripts/run/run_sim.py` — status line shows velocity availability.
- **Test** `tests/test_pico4_provider.py`, `tests/test_sim_loop.py`, `tests/test_cli_entrypoints.py` (Modify).

---

### Task 1: `PicoJoystickProvider` (CommandProvider)

**Files:**
- Create: `teleopit/commands/pico_joystick.py`
- Modify: `teleopit/commands/__init__.py`
- Test: `tests/test_pico_joystick_cmd.py`

**Interfaces:**
- Consumes: `Pico4InputProvider.get_controller_snapshot() -> PicoControllerSnapshot | None` (fields `left/right: PicoControllerState`, `timestamp_s: float`); `PicoControllerState` gains `axis_x`/`axis_y` in Task 2 — this task reads them via `getattr(state, "axis_x", 0.0)` so it works before and after Task 2 (defaults 0.0 → zero twist, safe).
- Produces: `PicoJoystickProvider(input_provider, *, deadzone=0.15, cmd_limits=None, max_age_s=0.5, clock=time.monotonic)` with `get_cmd() -> np.ndarray (6,) float32`, `reset()`, `close()` (satisfies `CommandProvider`).

Mapping contract (locked decision 2): left stick Y→lin_x, left stick X→lin_y, right stick X→ang_z; other twist components always 0. Stick range [-1,1]; deadzone rejects |stick| < 0.15 (edge = zero); linear map: positive stick s → `s * hi`, negative s → `s * |lo|` for axis limits [lo, hi].

- [ ] **Step 1: Write the failing tests**

```python
"""PicoJoystickProvider: pico sticks -> 6D twist with deadzone + disconnect-zero."""
from __future__ import annotations

import numpy as np

from teleopit.commands.pico_joystick import PicoJoystickProvider

_CMD_LIMITS = {"lin_vel_x": [-1.0, 2.0], "lin_vel_y": [-0.5, 0.5], "ang_vel_z": [-1.0, 1.0]}


class _State:
    def __init__(self, axis_x=0.0, axis_y=0.0, present=True):
        self.axis_x = float(axis_x)
        self.axis_y = float(axis_y)
        self.present = bool(present)
        self.raw = bool(present)


class _Snapshot:
    def __init__(self, left, right, timestamp_s=0.0, seq=0):
        self.left = left
        self.right = right
        self.timestamp_s = float(timestamp_s)
        self.seq = int(seq)


class _Provider:
    """Stands in for Pico4InputProvider."""

    def __init__(self, snapshot=None):
        self.snapshot = snapshot

    def get_controller_snapshot(self):
        return self.snapshot


def _provider(left=(0.0, 0.0), right=(0.0, 0.0), timestamp_s=0.0):
    return _Provider(_Snapshot(_State(*left), _State(*right), timestamp_s=timestamp_s))


def test_neutral_sticks_give_zero_twist():
    provider = PicoJoystickProvider(_provider(), cmd_limits=_CMD_LIMITS)
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_deadzone_rejects_small_sticks():
    provider = PicoJoystickProvider(_provider(left=(0.14, 0.14)), cmd_limits=_CMD_LIMITS)
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_deadzone_edge_is_zero():
    provider = PicoJoystickProvider(_provider(left=(0.15, -0.15)), cmd_limits=_CMD_LIMITS)
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_left_stick_y_maps_lin_x_asymmetric_limits():
    provider = PicoJoystickProvider(_provider(left=(0.0, 1.0)), cmd_limits=_CMD_LIMITS)
    np.testing.assert_allclose(provider.get_cmd()[0], 2.0)
    provider = PicoJoystickProvider(_provider(left=(0.0, -1.0)), cmd_limits=_CMD_LIMITS)
    np.testing.assert_allclose(provider.get_cmd()[0], -1.0)


def test_left_stick_x_maps_lin_y():
    provider = PicoJoystickProvider(_provider(left=(1.0, 0.0)), cmd_limits=_CMD_LIMITS)
    np.testing.assert_allclose(provider.get_cmd()[1], 0.5)


def test_right_stick_x_maps_ang_z():
    provider = PicoJoystickProvider(_provider(right=(0.8, 0.0)), cmd_limits=_CMD_LIMITS)
    np.testing.assert_allclose(provider.get_cmd()[5], 0.8)


def test_partial_stick_scales_linearly():
    provider = PicoJoystickProvider(_provider(left=(0.0, 0.5)), cmd_limits=_CMD_LIMITS)
    np.testing.assert_allclose(provider.get_cmd()[0], 1.0)


def test_no_snapshot_reads_zero():
    provider = PicoJoystickProvider(_Provider(None), cmd_limits=_CMD_LIMITS)
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_disconnected_controllers_read_zero():
    provider = PicoJoystickProvider(_provider(), cmd_limits=_CMD_LIMITS)
    provider._input_provider.snapshot = _Snapshot(_State(present=False), _State(present=False))
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_stale_snapshot_reads_zero():
    provider = PicoJoystickProvider(_provider(left=(0.0, 1.0)), cmd_limits=_CMD_LIMITS)
    provider._input_provider.snapshot.timestamp_s = -10.0
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_missing_axis_attr_reads_zero():
    class _LegacyState:
        present = True
        # no axis_x/axis_y — pre-Task-2 snapshot shape

    provider = PicoJoystickProvider(
        _Provider(_Snapshot(_LegacyState(), _LegacyState())), cmd_limits=_CMD_LIMITS
    )
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_default_cmd_limits_used_when_none():
    provider = PicoJoystickProvider(_provider(left=(0.0, 1.0)))
    np.testing.assert_allclose(provider.get_cmd()[0], 2.0)


def test_reset_and_close_are_safe():
    provider = PicoJoystickProvider(_provider(left=(0.0, 1.0)), cmd_limits=_CMD_LIMITS)
    provider.get_cmd()
    provider.reset()
    provider.close()
    assert provider.get_cmd().shape == (6,)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_pico_joystick_cmd.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teleopit.commands.pico_joystick'`

- [ ] **Step 3: Write the implementation**

`teleopit/commands/pico_joystick.py`:

```python
"""Pico joystick twist source: controller sticks -> 6D body-frame twist.

Left stick = translation (Y -> lin_x push-forward, X -> lin_y), right stick X
-> ang_z. Sticks in [-1, 1] pass a deadzone, then map linearly onto the
policy cmd limits (asymmetric per-axis: stick +1 -> hi, stick -1 -> lo).

Zero-command guarantees (locked decision 4): no snapshot yet, controllers
absent, or a snapshot older than `max_age_s` all read as zero twist — the
robot stands still on disconnect; nothing auto-exits VELOCITY mode.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

_DEFAULT_DEADZONE = 0.15
_DEFAULT_CMD_LIMITS = {
    "lin_vel_x": [-1.0, 2.0],
    "lin_vel_y": [-0.5, 0.5],
    "ang_vel_z": [-1.0, 1.0],
}


def _deadzone(value: float, deadzone: float) -> float:
    return 0.0 if abs(value) < deadzone else value


class PicoJoystickProvider:
    """Maps Pico controller thumbsticks onto the CommandProvider twist seam."""

    def __init__(
        self,
        input_provider: Any,
        *,
        deadzone: float = _DEFAULT_DEADZONE,
        cmd_limits: dict[str, list[float]] | None = None,
        max_age_s: float = 0.5,
        clock: Any = time.monotonic,
    ) -> None:
        if not 0.0 <= float(deadzone) < 1.0:
            raise ValueError(f"deadzone must be in [0, 1), got {deadzone}")
        self._input_provider = input_provider
        self._deadzone = float(deadzone)
        limits = dict(_DEFAULT_CMD_LIMITS)
        if cmd_limits:
            limits.update(cmd_limits)
        self._lin_x = (float(limits["lin_vel_x"][0]), float(limits["lin_vel_x"][1]))
        self._lin_y = (float(limits["lin_vel_y"][0]), float(limits["lin_vel_y"][1]))
        self._ang_z = (float(limits["ang_vel_z"][0]), float(limits["ang_vel_z"][1]))
        self._max_age_s = float(max_age_s)
        self._clock = clock

    @staticmethod
    def _scale(stick: float, lo: float, hi: float) -> float:
        """Linear map stick [-1,1] onto [lo, hi], asymmetric at zero."""
        return float(stick * hi if stick >= 0.0 else stick * abs(lo))

    def _read_sticks(self) -> tuple[float, float, float] | None:
        """Return (left_x, left_y, right_x), or None when data is unusable."""
        get_snapshot = getattr(self._input_provider, "get_controller_snapshot", None)
        if not callable(get_snapshot):
            return None
        snapshot = get_snapshot()
        if snapshot is None:
            return None
        if self._max_age_s > 0.0:
            age = float(self._clock()) - float(snapshot.timestamp_s)
            if age > self._max_age_s:
                return None
        left = getattr(snapshot, "left", None)
        right = getattr(snapshot, "right", None)
        if left is None or right is None:
            return None
        if not (bool(getattr(left, "present", False)) and bool(getattr(right, "present", False))):
            return None
        left_x = _deadzone(float(getattr(left, "axis_x", 0.0)), self._deadzone)
        left_y = _deadzone(float(getattr(left, "axis_y", 0.0)), self._deadzone)
        right_x = _deadzone(float(getattr(right, "axis_x", 0.0)), self._deadzone)
        return left_x, left_y, right_x

    def get_cmd(self) -> np.ndarray:
        cmd = np.zeros(6, dtype=np.float32)
        sticks = self._read_sticks()
        if sticks is None:
            return cmd
        left_x, left_y, right_x = sticks
        cmd[0] = self._scale(left_y, *self._lin_x)
        cmd[1] = self._scale(left_x, *self._lin_y)
        cmd[5] = self._scale(right_x, *self._ang_z)
        return cmd

    def reset(self) -> None:
        return None  # stateless: every get_cmd re-reads the snapshot

    def close(self) -> None:
        return None  # input provider owns the bridge lifetime
```

Timestamp domain note: `PicoControllerSnapshot.timestamp_s` comes from `frame.receive_time_s` (`pico4_provider.py:444`), which is already `time.monotonic()` domain, so monotonic age comparison is correct.

`teleopit/commands/__init__.py` becomes:

```python
from teleopit.commands.base import CommandProvider, TwistCommand
from teleopit.commands.keyboard_cmd import KeyboardTwistProvider
from teleopit.commands.pico_joystick import PicoJoystickProvider

__all__ = ["CommandProvider", "TwistCommand", "KeyboardTwistProvider", "PicoJoystickProvider"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_pico_joystick_cmd.py -v`
Expected: 14 PASS

- [ ] **Step 5: Commit**

```bash
git add teleopit/commands/pico_joystick.py teleopit/commands/__init__.py tests/test_pico_joystick_cmd.py
git commit -m "feat(commands): PicoJoystickProvider maps pico sticks to twist cmd"
```

---

### Task 2: Expose `axis_x`/`axis_y` in `PicoControllerState`

**Files:**
- Modify: `teleopit/inputs/pico4_provider.py` — `PicoControllerState` (:58-65) and `_read_controller_state` (:611-619)
- Test: `tests/test_pico4_provider.py`

**Interfaces:**
- Consumes: pico_bridge `ControllerState.axis: dict[str, float]` keys `"x"`, `"y"` (verified in installed `pico_bridge/frames.py:281-286`).
- Produces: `PicoControllerState(raw, grip, trigger, present=True, axis_x=0.0, axis_y=0.0)` — additive defaulted fields, existing constructors unaffected.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_pico4_provider.py`; first read the file and match its existing fake-controller fixture style)

```python
def test_controller_state_exposes_primary_2d_axis():
    from teleopit.inputs.pico4_provider import Pico4InputProvider

    class _Controller:
        raw = True
        axis = {"x": 0.25, "y": -0.75, "grip": 0.1, "trigger": 0.2}

    state = Pico4InputProvider._read_controller_state(_Controller())
    assert state.axis_x == pytest.approx(0.25)
    assert state.axis_y == pytest.approx(-0.75)
    assert state.grip == pytest.approx(0.1)
    assert state.present is True


def test_controller_state_absent_controller_defaults_zero_axis():
    from teleopit.inputs.pico4_provider import Pico4InputProvider

    state = Pico4InputProvider._read_controller_state(None)
    assert state.axis_x == 0.0
    assert state.axis_y == 0.0
    assert state.present is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_pico4_provider.py -k "primary_2d_axis or absent_controller" -v`
Expected: FAIL — `AttributeError: ... no attribute 'axis_x'`

- [ ] **Step 3: Implement**

`PicoControllerState`:

```python
@dataclass(frozen=True)
class PicoControllerState:
    """Latest per-controller input state exposed by pico_bridge."""

    raw: bool
    grip: float
    trigger: float
    present: bool = True
    axis_x: float = 0.0
    axis_y: float = 0.0
```

`_read_controller_state`:

```python
    @staticmethod
    def _read_controller_state(controller: Any) -> PicoControllerState:
        axis = {} if controller is None else getattr(controller, "axis", {}) or {}
        return PicoControllerState(
            raw=bool(False if controller is None else getattr(controller, "raw", False)),
            grip=float(axis.get("grip", 0.0)),
            trigger=float(axis.get("trigger", 0.0)),
            present=controller is not None,
            axis_x=float(axis.get("x", 0.0)),
            axis_y=float(axis.get("y", 0.0)),
        )
```

- [ ] **Step 4: Run the full provider test file**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_pico4_provider.py -v`
Expected: all PASS (additive defaulted fields).

- [ ] **Step 5: Commit**

```bash
git add teleopit/inputs/pico4_provider.py tests/test_pico4_provider.py
git commit -m "feat(inputs): surface pico primary2DAxis as axis_x/axis_y"
```

---

### Task 3: Extract `VelocityStepController` (shared step core)

**Files:**
- Create: `teleopit/sim/velocity_step.py`
- Modify: `teleopit/sim/velocity_session.py`
- Test: `tests/test_velocity_step.py` (Create); `tests/test_velocity_session.py` must stay green with NO edits (regression gate)

**Interfaces:**
- Consumes: `PolicyStepRunner` public surface, `CommandProvider`, `StandingReferenceInterpolator.from_hold`, `ref_proc.dispatch_build_observation`.
- Produces:
  - `VelocityStepController(*, velocity_runner, cmd_provider, pose_b: np.ndarray, policy_hz: float, transition_duration_s: float, joint_vel_limit: float, tilt_threshold_rad: float)`
  - `pose_b_qpos` (property), `standing_qpos_of_pose(joint_pose)`, `current_hold_qpos(state)` (static)
  - `arm_standing_interpolator(hold_qpos, target_qpos) -> StandingReferenceInterpolator`
  - `velocity_prev_action_seed(mimic_runner) -> np.ndarray (29,) float32`
  - `begin_velocity_handoff(mimic_runner, hold_qpos) -> None`
  - `check_safety(state) -> str | None` — returns `"stop"` (joint-vel) / `"standing"` (tilt) / None; does NOT mutate mode
  - `velocity_step(robot) -> tuple[np.ndarray, np.ndarray, np.ndarray, object]` — returns `(cmd, action, target, final_state)` for caller-side metrics
  - `standing_step(robot, mimic_runner, standing_ref_qpos, interpolator, steps_in_mode) -> tuple[np.ndarray, StandingReferenceInterpolator | None, np.ndarray, object]` — returns `(updated_standing_ref, updated_interpolator, target, final_state)`

Extraction = verbatim moves from `velocity_session.py`, with these exact sources:
- `standing_qpos_of_pose` ← `:116-121`; `current_hold_qpos` ← `:123-132`
- `arm_standing_interpolator` ← the `from_hold` call in `_apply_pending_mode` `:191-194`
- `velocity_prev_action_seed` ← `:138-171` (rename `self._velocity_runner`→`self.velocity_runner`, `self._pose_b`→`self._pose_b`, arg `mimic_runner` replaces `self._mimic_runner`)
- `tilt_angle` ← `:219-224` (becomes `@staticmethod`)
- `check_safety` ← `:226-239` minus the `request_mode` calls (return strings + keep the two `logger.error` lines)
- `velocity_step` ← `:304-319` minus `_apply_perturbation`/`_record_metrics`/`_track_root_height` (caller does those), returning the 4-tuple
- `standing_step` ← `_standing_step` `:245-272` + `_mimic_runner_build_obs` `:274-302`, parameterized by `(robot, mimic_runner, standing_ref_qpos, interpolator, steps_in_mode)`, adopting the interpolator endpoint exactly as `:250-259` does, returning the 4-tuple

`VelocitySimSession` keeps: mode enum, `request_mode`, `_apply_pending_mode` (now delegating), perturbation (T), metrics, keyboard, `run()`. Its `_velocity_step` becomes:

```python
    def _velocity_step(self) -> None:
        state = self._robot.get_state()
        cmd, action, target, final_state = self._steps.velocity_step(self._robot)
        self._record_metrics(target, state, cmd=cmd)
        self._track_root_height(final_state)
```

and `_standing_step`:

```python
    def _standing_step(self) -> None:
        state = self._robot.get_state()
        self._standing_ref_qpos, self._interpolator, target, final_state = self._steps.standing_step(
            self._robot, self._mimic_runner, self._standing_ref_qpos,
            self._interpolator, self._steps_in_mode,
        )
        self._record_metrics(target, state, cmd=None)
        self._track_root_height(final_state)
```

`_apply_pending_mode` arms via `self._steps.arm_standing_interpolator(self._steps.current_hold_qpos(state), self._steps.pose_b_qpos)` and for the VELOCITY target calls `self._steps.begin_velocity_handoff(self._mimic_runner, hold)` then keeps its own `self._mimic_runner.controller.reset()` etc. exactly as today for the STANDING target. `_check_safety` becomes a thin adapter:

```python
    def _check_safety(self, state: Any) -> None:
        if self.mode != VelocityMode.VELOCITY:
            return
        verdict = self._steps.check_safety(state)
        if verdict == "stop":
            self.request_mode(VelocityMode.STOP)
        elif verdict == "standing":
            self.request_mode(VelocityMode.STANDING)
```

- [ ] **Step 1: Write failing tests** — `tests/test_velocity_step.py`. Copy verbatim from `tests/test_velocity_session.py`: `POSE_B` (:19-31), `_ZERO_CMD` (:33), `_StubController`, `_StubMimicObsBuilder`, `_StubTwistObsBuilder`, `_StubRobot`, `_StubPrep`, `_StubRunner`, `_StubCmd` (:44-186). Then:

```python
def _controller(**kwargs):
    robot = _StubRobot()
    vel_runner = _StubRunner(robot, _StubController(98, action_scale=1.0), _StubTwistObsBuilder(98))
    defaults = dict(
        velocity_runner=vel_runner,
        cmd_provider=_StubCmd([0.0] * 6),
        pose_b=POSE_B.copy(),
        policy_hz=50.0,
        transition_duration_s=1.0,
        joint_vel_limit=10.0,
        tilt_threshold_rad=1.0,
    )
    defaults.update(kwargs)
    return VelocityStepController(**defaults), robot, vel_runner


def _mimic_runner(robot, pose_a=None):
    return _StubRunner(
        robot, _StubController(167, action_scale=1.0, default_dof_pos=pose_a),
        _StubMimicObsBuilder(167),
    )


def test_seed_joint_space_equivalent_of_mimic_action():
    robot = _StubRobot()
    mimic_runner = _mimic_runner(robot, pose_a=np.full(29, 0.1))
    mimic_runner.last_action = np.full(29, 0.3, dtype=np.float32)
    ctrl, _, _ = _controller()
    np.testing.assert_allclose(
        ctrl.velocity_prev_action_seed(mimic_runner),
        (0.3 + np.full(29, 0.1) - POSE_B).astype(np.float32),
    )


def test_seed_falls_back_to_zeros_without_mimic_default():
    robot = _StubRobot()
    mimic_runner = _mimic_runner(robot, pose_a=None)
    ctrl, _, _ = _controller()
    np.testing.assert_allclose(
        ctrl.velocity_prev_action_seed(mimic_runner), np.zeros(29, dtype=np.float32)
    )


def test_begin_velocity_handoff_seeds_and_resets():
    robot = _StubRobot()
    mimic_runner = _mimic_runner(robot, pose_a=np.full(29, 0.1))
    mimic_runner.last_action = np.full(29, 0.3, dtype=np.float32)
    ctrl, _, vel_runner = _controller()
    ctrl.begin_velocity_handoff(mimic_runner, np.zeros(43))
    assert vel_runner.controller.reset_called == 1
    assert vel_runner.obs_builder.reset_called == 1
    np.testing.assert_allclose(
        vel_runner.last_action, (0.3 + np.full(29, 0.1) - POSE_B).astype(np.float32)
    )


def test_velocity_step_runs_full_twist_pipeline():
    ctrl, robot, vel_runner = _controller(cmd_provider=_StubCmd([1.0, 0, 0, 0, 0, 0]))
    cmd, action, target, final_state = ctrl.velocity_step(robot)
    assert robot.steps == 1
    assert len(vel_runner.obs_builder.cmds) == 1
    np.testing.assert_allclose(cmd[:3], [1.0, 0, 0])


def test_check_safety_joint_vel_returns_stop():
    class _FastRobot(_StubRobot):
        def get_state(self):
            from teleopit.interfaces import RobotState
            return RobotState(
                qpos=self.qpos, qvel=np.full(29, 20.0),
                quat=np.array([1.0, 0, 0, 0]), ang_vel=np.zeros(3),
                timestamp=0.0, base_pos=np.array([0, 0, 0.75]),
            )

    ctrl, _, _ = _controller()
    assert ctrl.check_safety(_FastRobot().get_state()) == "stop"


def test_check_safety_tilt_returns_standing():
    ctrl, _, _ = _controller()
    tilted = _StubRobot()
    tilted.tilted = True
    assert ctrl.check_safety(tilted.get_state()) == "standing"


def test_check_safety_healthy_returns_none():
    ctrl, _, _ = _controller()
    assert ctrl.check_safety(_StubRobot().get_state()) is None


def test_standing_step_interpolates_then_adopts_endpoint():
    ctrl, robot, _ = _controller()
    mimic_runner = _mimic_runner(robot, pose_a=np.zeros(29))
    standing_ref = np.zeros(43)
    interpolator = ctrl.arm_standing_interpolator(standing_ref, ctrl.pose_b_qpos)
    ref, interp, _, _ = ctrl.standing_step(
        robot, mimic_runner, standing_ref, interpolator, steps_in_mode=100
    )
    assert interp is None  # 100 steps * 0.02 s = 2 s > 1 s duration: finished
    assert not np.array_equal(ref, standing_ref)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_velocity_step.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teleopit.sim.velocity_step'`

- [ ] **Step 3: Implement** `teleopit/sim/velocity_step.py` per the interface block above (verbatim moves). Module docstring explains the dual-entry contract. Then rewrite `VelocitySimSession` to delegate per the snippets above.

- [ ] **Step 4: Run the three velocity test files**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_velocity_step.py tests/test_velocity_session.py -v`
Expected: test_velocity_step 8/8 PASS; test_velocity_session 22/22 PASS with zero edits to that file (regression gate).

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_velocity_integration.py -m slow -v`
Expected: 3/3 PASS (assets present at `ckpt/track_g1.onnx` + `assets/policies/velocity_v1/policy.onnx`; ~2-5 min).

- [ ] **Step 5: Commit**

```bash
git add teleopit/sim/velocity_step.py teleopit/sim/velocity_session.py tests/test_velocity_step.py
git commit -m "refactor(sim): extract VelocityStepController shared step core"
```

---

### Task 4: `SimulationMode.VELOCITY` + `SimLoopSession` mode branch

**Files:**
- Modify: `teleopit/sim/loop.py` (enum :35-39, `attach_velocity_stack`)
- Modify: `teleopit/sim/session.py` (mode methods, keyboard :316-348, run branch :630+, standing fetch)
- Test: `tests/test_sim_loop.py`

**Interfaces:**
- Consumes: `VelocityStepController` (Task 3), `PolicyStepRunner`, existing `enter_standing_mode`/`enter_mocap_mode`/`reset_policy_reference_state`.
- Produces:
  - `SimulationMode.VELOCITY = "velocity"`
  - `SimulationLoop.attach_velocity_stack(*, velocity_controller, velocity_obs_builder, cmd_provider, transition_duration_s, joint_vel_limit, tilt_threshold_rad, pose_b) -> VelocityStepController` — builds a second `PolicyStepRunner` over the same robot; `RuntimeError` if called twice. (Constructor initializes `_velocity_controller = None`, `_velocity_obs_builder = None`, `_velocity_step_controller = None` so all existing construction sites are unchanged.)
  - `SimLoopSession.enter_velocity_mode() -> bool`, `SimLoopSession.exit_velocity_to_standing() -> None`

Behavioral contract (locked decisions 1/3/4):
1. V honored ONLY in STANDING; in MOCAP/ARMS → console feedback `("V", "velocity", result="requires STANDING")`, no state change. MOCAP→VELOCITY direct switch forbidden.
2. In VELOCITY the session skips the mimic policy step but keeps consuming pico packets (skeleton viewer live, reference timeline warm for MOCAP return) and never gates on warmup (`should_continue` path bypassed): a quiet stream must not stall the twist step.
3. X from VELOCITY → `exit_velocity_to_standing()`: arm `arm_standing_interpolator(current_hold, pose_b_qpos)` (yaw-preserving), set `loop._standing_qpos` to the pose-B endpoint so the STANDING fetch holds pose B, reset mimic policy state, mode = STANDING. The pose-B ramp then plays through `_fetch_standing_input`, which must sample the active interpolator (see below). X from MOCAP/ARMS keeps today's `enter_standing_mode()` exactly.
4. Disconnect mid-VELOCITY: joystick reads zero (Task 1), robot stands still; NO auto mode-exit.
5. Safety per step (VELOCITY only): joint-vel → end session (`playback_stop_requested = True` + console event); tilt → `exit_velocity_to_standing()`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_sim_loop.py`, reusing `_DummyRobot`/`_DummyController`/`_DummyObsBuilder`/`_DummyRetargeter` and the monkeypatched-keyboard pattern from `test_simulation_loop_realtime_keyboard_mode_transitions` :563):

```python
class _DummyTwistBuilder:
    """TwistCmdObservationBuilder stub: build(state, cmd, last_action)."""

    def __init__(self) -> None:
        self.total_obs_size = 6
        self.cmds: list[np.ndarray] = []
        self.reset_called = 0

    def reset(self) -> None:
        self.reset_called += 1

    def build(self, state, cmd, last_action):
        self.cmds.append(np.asarray(cmd, dtype=np.float32).copy())
        return np.zeros(6, dtype=np.float32)


class _DummyVelocityController:
    _expected_obs_dim = 6
    action_scale = np.ones(2, dtype=np.float32)
    default_dof_pos = np.zeros(2, dtype=np.float32)

    def __init__(self) -> None:
        self.compute_called = 0
        self.reset_called = 0

    def compute_action(self, obs):
        self.compute_called += 1
        return np.array([0.05, -0.05], dtype=np.float32)

    def reset(self) -> None:
        self.reset_called += 1

    def get_target_dof_pos(self, action):
        return np.asarray(action, dtype=np.float32)


class _ConstCmdProvider:
    def __init__(self, cmd):
        self._cmd = np.asarray(cmd, dtype=np.float32)

    def get_cmd(self):
        return self._cmd

    def reset(self):
        pass

    def close(self):
        pass


def _velocity_loop(monkeypatch, keyboard_script):
    from teleopit.sim.loop import SimulationLoop

    class _KeyboardReader:
        def __init__(self, script):
            self._script = list(script)
            self.active = True

        def poll(self):
            return self._script.pop(0) if self._script else ()

        def close(self):
            pass

    monkeypatch.setattr("teleopit.sim.session.TerminalKeyboardReader", _KeyboardReader)

    class _CountingPicoProvider:
        fps = 1
        packet_calls = 0

        def get_realtime_input_packet(self):
            _CountingPicoProvider.packet_calls += 1
            return RealtimeInputPacket(
                frame={"Pelvis": (np.zeros(3, dtype=np.float32), np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))},
                timestamp_s=0.0, seq=0, control_events=(),
            )

    loop = SimulationLoop(
        robot=_DummyRobot(),
        controller=_DummyController(),
        obs_builder=_DummyObsBuilder(),
        bus=InProcessBus(),
        cfg={"policy_hz": 50.0, "pd_hz": 50.0, "realtime": False,
             "retarget_buffer_enabled": False, "keyboard": {"enabled": True}},
        viewers=set(),
    )
    twist_builder = _DummyTwistBuilder()
    vel_controller = _DummyVelocityController()
    loop.attach_velocity_stack(
        velocity_controller=vel_controller,
        velocity_obs_builder=twist_builder,
        cmd_provider=_ConstCmdProvider([0.5, 0.0, 0.0, 0.0, 0.0, 0.0]),
        transition_duration_s=1.0,
        joint_vel_limit=10.0,
        tilt_threshold_rad=1.0,
        pose_b=np.zeros(2, dtype=np.float64),
    )
    return loop, twist_builder, vel_controller, _CountingPicoProvider()


def test_v_enters_velocity_from_standing_and_steps_twist(monkeypatch) -> None:
    from teleopit.sim.loop import SimulationMode

    loop, twist_builder, vel_controller, provider = _velocity_loop(
        monkeypatch, [(TerminalKeyEvent("v"),)]
    )
    result = loop.run(input_provider=provider, retargeter=_DummyRetargeter(), num_steps=3)
    assert result["steps"] == 3
    assert loop.last_session.simulation_mode == SimulationMode.VELOCITY
    assert vel_controller.compute_called == 3          # twist policy ran every step
    assert len(twist_builder.cmds) == 3
    np.testing.assert_allclose(twist_builder.cmds[0][:3], [0.5, 0.0, 0.0])
    assert _CountingPicoProvider.packet_calls >= 3      # pico stream still consumed


def test_v_rejected_from_mocap(monkeypatch) -> None:
    from teleopit.sim.loop import SimulationMode

    loop, twist_builder, vel_controller, provider = _velocity_loop(
        monkeypatch, [(TerminalKeyEvent("y"),), (TerminalKeyEvent("v"),)]
    )
    result = loop.run(input_provider=provider, retargeter=_DummyRetargeter(), num_steps=3)
    assert loop.last_session.simulation_mode == SimulationMode.MOCAP
    assert vel_controller.compute_called == 0           # no twist step ever ran


def test_x_returns_velocity_to_standing(monkeypatch) -> None:
    from teleopit.sim.loop import SimulationMode

    loop, _, vel_controller, provider = _velocity_loop(
        monkeypatch, [(TerminalKeyEvent("v"),), (TerminalKeyEvent("x"),)]
    )
    result = loop.run(input_provider=provider, retargeter=_DummyRetargeter(), num_steps=4)
    assert loop.last_session.simulation_mode == SimulationMode.STANDING
    assert 0 < vel_controller.compute_called < 4        # twist ran, then stopped


def test_velocity_mode_survives_quiet_input_stream(monkeypatch) -> None:
    """Warmup gating must not stall the twist step when packets go quiet."""
    from teleopit.sim.loop import SimulationMode

    class _OneShotProvider:
        fps = 1

        def __init__(self):
            self.calls = 0

        def get_realtime_input_packet(self):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("stream went quiet")  # fetch fails; step must not
            return RealtimeInputPacket(
                frame={"Pelvis": (np.zeros(3, dtype=np.float32), np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))},
                timestamp_s=0.0, seq=0, control_events=(),
            )

    loop, _, vel_controller, _ = _velocity_loop(monkeypatch, [(TerminalKeyEvent("v"),)])
    provider = _OneShotProvider()
    result = loop.run(input_provider=provider, retargeter=_DummyRetargeter(), num_steps=3)
    assert result["steps"] == 3
    assert vel_controller.compute_called == 3
```

Note: `loop.last_session` — add `self.last_session = session` in `SimulationLoop.run()` (one line) so tests can assert the final mode; alternatively assert via the result dict if you prefer adding a `final_mode` key. Pick `last_session` (no result-dict change, keeps summary keys stable for other tests).

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_sim_loop.py -k "velocity or _v_" -v`
Expected: FAIL — `AttributeError: 'SimulationLoop' object has no attribute 'attach_velocity_stack'`

- [ ] **Step 3: Implement**

**loop.py** — enum gains `VELOCITY = "velocity"`; `__init__` (after `_init_components(self, viewers)`) initializes the three velocity attrs to `None`; new method:

```python
    def attach_velocity_stack(
        self,
        *,
        velocity_controller: object,
        velocity_obs_builder: object,
        cmd_provider: object,
        transition_duration_s: float,
        joint_vel_limit: float,
        tilt_threshold_rad: float,
        pose_b: Float64Array,
    ) -> object:
        """Build the twist-policy runner + shared step controller (task #6).

        Optional: without this call the loop behaves exactly as before.
        """
        if self._velocity_step_controller is not None:
            raise RuntimeError("velocity stack already attached")
        from teleopit.sim.velocity_step import VelocityStepController

        velocity_runner = PolicyStepRunner(
            robot=self.robot,
            controller=cast(object, velocity_controller),
            obs_builder=cast(object, velocity_obs_builder),
            policy_hz=self.policy_hz,
            decimation=self.decimation,
            num_actions=self._num_actions,
            kps=self._kps,
            kds=self._kds,
            torque_limits=self._torque_limits,
            default_dof_pos=np.asarray(pose_b, dtype=np.float32),
        )
        step_controller = VelocityStepController(
            velocity_runner=velocity_runner,
            cmd_provider=cmd_provider,
            pose_b=pose_b,
            policy_hz=self.policy_hz,
            transition_duration_s=transition_duration_s,
            joint_vel_limit=joint_vel_limit,
            tilt_threshold_rad=tilt_threshold_rad,
        )
        self._velocity_controller = velocity_controller
        self._velocity_obs_builder = velocity_obs_builder
        self._velocity_step_controller = step_controller
        return step_controller
```

And in `run()`: `session = SimLoopSession(...)`; add `self.last_session = session`; `return session.run()`.

**session.py** — `__init__` additions (after `self.mocap_session`, :163):

```python
        # VELOCITY-mode state (None stack => mode unreachable)
        self.velocity_steps = loop._velocity_step_controller
        self._velocity_interpolator = None
        self._velocity_standing_ref: Float64Array | None = None
        self._steps_in_mode = 0
```

Mode methods (next to `enter_standing_mode`, :241):

```python
    def enter_velocity_mode(self) -> bool:
        from teleopit.sim.loop import SimulationMode
        if self.velocity_steps is None:
            self._loop._console.key_feedback("V", "velocity", result="no velocity stack")
            return False
        if self.simulation_mode != SimulationMode.STANDING:
            # Locked decision 3: STANDING is the only validated hand-off;
            # MOCAP->VELOCITY direct switching is forbidden.
            _logger.info(
                "Ignoring V: VELOCITY entry requires STANDING (current=%s)",
                self.simulation_mode.value,
            )
            self._loop._console.key_feedback("V", "velocity", result="requires STANDING")
            return False
        steps = self.velocity_steps
        hold = steps.current_hold_qpos(self._loop.robot.get_state())
        steps.begin_velocity_handoff(self._step_runner, hold)
        self.simulation_mode = SimulationMode.VELOCITY
        self._steps_in_mode = 0
        _logger.info("Simulation mode -> VELOCITY")
        return True

    def exit_velocity_to_standing(self) -> None:
        from teleopit.sim.loop import SimulationMode
        steps = self.velocity_steps
        hold = steps.current_hold_qpos(self._loop.robot.get_state())
        # Ramp into pose-B standing, yaw-aligned to the robot's current heading
        # (NOT the mimic standing reference): the target never snaps back to
        # world yaw 0 after a walk, and pose B is the velocity policy's home.
        self._velocity_interpolator = steps.arm_standing_interpolator(
            hold, steps.pose_b_qpos
        )
        self._velocity_standing_ref = steps.pose_b_qpos.copy()
        self.reset_policy_reference_state(reset_mocap_session=True)
        self._loop._standing_qpos = steps.pose_b_qpos.copy()
        self.simulation_mode = SimulationMode.STANDING
        self._steps_in_mode = 0
        _logger.info("Simulation mode -> STANDING (from VELOCITY)")
```

Keyboard routing (`_handle_realtime_keyboard`, replace :329-348 body):

```python
            if self.simulation_mode == SimulationMode.STANDING:
                if key == "y":
                    if self.enter_mocap_mode():
                        self._loop._console.key_feedback("Y", "mocap", result="MOCAP")
                    else:
                        self._loop._console.key_feedback("Y", "mocap", result="waiting for input")
                elif key == "v":
                    if self.enter_velocity_mode():
                        self._loop._console.key_feedback("V", "velocity", result="VELOCITY")
                continue
            if self.simulation_mode == SimulationMode.VELOCITY:
                if key == "x":
                    self.exit_velocity_to_standing()
                    self._loop._console.key_feedback("X", "standing", result="STANDING")
                    continue
                if key == "a":
                    self._loop._console.key_feedback("A", "pause/resume", result="ignored (VELOCITY)")
                    continue
                if key == "b":
                    self._loop._console.key_feedback("B", "arms", result="ignored (VELOCITY)")
                    continue
                continue  # q/h handled above; VELOCITY has no other keys
            if key == "x":
                self.enter_standing_mode()
                self._loop._console.key_feedback("X", "standing", result="STANDING")
                continue
            if key == "b":
                if self.toggle_arms_mode():
                    self._loop._console.key_feedback("B", "arms", result=self.simulation_mode.value.upper())
                else:
                    self._loop._console.key_feedback("B", "arms", result="ignored")
                continue
            if key == "a":
                self._loop._console.key_feedback("A", "pause/resume", result=self.toggle_realtime_mocap_pause())
```

`_fetch_standing_input` (:409-416) — sample the active pose-B ramp before holding:

```python
    def _fetch_standing_input(self) -> tuple[bool, ReferenceWindow | None, RealtimeReferenceDiagnostics | None]:
        self.cached_human_frame = None
        if self._velocity_interpolator is not None:
            # Pose-B ramp after X-from-VELOCITY: same pattern as
            # VelocitySimSession._standing_step adoption logic.
            t_s = self._steps_in_mode * self.policy_dt
            qpos = np.asarray(self._velocity_interpolator.sample(t_s), dtype=np.float64)
            if self._velocity_interpolator.finished(t_s):
                self._velocity_standing_ref = qpos.copy()
                self._velocity_interpolator = None
            self.cached_retargeted = qpos
            return False, None, None
        if self._loop._standing_qpos is None:
            self.cached_retargeted = self._loop._set_standing_reference(self._loop.robot.get_state())
        else:
            self.cached_retargeted = self._loop._standing_qpos.copy()
        return False, None, None
```

run() loop — two insertions. (a) After the keyboard block (:602-614), no change needed (keyboard handles V/X). (b) Input fetch + step selection (:630-671): insert a VELOCITY-first branch:

```python
                if (
                    self.realtime_keyboard_mode_enabled
                    and self.simulation_mode == SimulationMode.VELOCITY
                ):
                    self._fetch_realtime_input_quiet()
                    if self._velocity_safety_and_step():
                        break
                elif self.realtime_keyboard_mode_enabled and self.simulation_mode == SimulationMode.STANDING:
                    ...  # existing standing branch unchanged
```

(the existing `if/elif/else` chain at :630-649 gains this VELOCITY case as the first branch; everything else identical). Helpers:

```python
    def _fetch_realtime_input_quiet(self) -> None:
        """Keep the pico stream warm in VELOCITY (viewer + timeline), no gating.

        Failures are swallowed: a quiet/disconnected stream must never stall
        the twist step (locked decision 4 — robot stands still, no auto exit).
        """
        try:
            loop = self._loop
            packet = loop._fetch_realtime_input_packet(
                self._input_provider, self.last_live_packet_seq
            )
            frame_seq = int(packet.seq)
            if frame_seq != self.last_live_packet_seq:
                human_frame = cast(dict, packet.frame)
                retargeted_qpos = self._step_runner._retarget_to_qpos(
                    self._retargeter.retarget(human_frame)
                )
                if self.reference_timeline is not None:
                    self.reference_timeline.append(retargeted_qpos, float(packet.timestamp_s))
                    if self.realtime_reference_manager is not None:
                        self.realtime_reference_manager.note_realtime_frame()
                self.latest_live_human_frame = human_frame
                self.latest_live_timestamp = float(packet.timestamp_s)
                self.last_live_packet_seq = frame_seq
                self._viewer_manager.write_mocap(
                    cast(object, self._input_provider), human_frame
                )
        except Exception:
            _logger.debug("velocity-mode input fetch skipped (stream quiet)", exc_info=True)

    def _velocity_safety_and_step(self) -> bool:
        """One VELOCITY iteration: safety check, twist step, viewer writes.

        Returns True when the session must end (joint-vel safety STOP).
        """
        steps = self.velocity_steps
        assert steps is not None
        verdict = steps.check_safety(self._loop.robot.get_state())
        if verdict == "stop":
            _logger.error("VELOCITY safety stop: joint velocity over limit -> ending session")
            self._loop._console.key_feedback("SAFETY", "joint-vel", result="session end")
            self.playback_stop_requested = True
            return True
        if verdict == "standing":
            _logger.error("VELOCITY tilt safety -> STANDING")
            self.exit_velocity_to_standing()
            return False
        _, _, _, final_state = steps.velocity_step(self._loop.robot)
        self._viewer_manager.write_sim2sim(self._loop.robot)
        self._viewer_manager.write_camera(self._loop.robot)
        if self._loop._video_runtime is not None:
            self._loop._video_runtime.tick()
        self._steps_in_mode += 1
        return False
```

After the branch, the shared pacing block (:714-719) paces the step; skip the mimic-only tail (publisher/debug write for the mimic path stay in their branch — the VELOCITY branch does its own viewer writes above and must NOT fall through to `finish_step`/`steps_done` duplication: increment `self.steps_done` at the same place the loop already does (:733) and `continue` past the mimic step body). Concretely, wrap so that when the VELOCITY branch ran, execution jumps directly to the pacing + `steps_done += 1` tail.

- [ ] **Step 4: Run the sim loop tests**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_sim_loop.py -v`
Expected: all existing tests PASS (mocap path untouched — this is the zero-mocap-change gate) + 4 new velocity tests PASS.

- [ ] **Step 5: Commit**

```bash
git add teleopit/sim/loop.py teleopit/sim/session.py tests/test_sim_loop.py
git commit -m "feat(sim): VELOCITY as 4th SimulationMode with V/X switching"
```

---

### Task 5: Pipeline wiring + `pico4_sim_velocity.yaml` launch config

**Files:**
- Create: `teleopit/configs/pico4_sim_velocity.yaml`
- Modify: `teleopit/pipeline.py`, `teleopit/runtime/factory.py` (public wrapper), `teleopit/runtime/console.py:210-223`, `scripts/run/run_sim.py:16-32`
- Test: `tests/test_cli_entrypoints.py`

**Interfaces:**
- Consumes: `build_velocity_components`-style policy build (factory), `PicoJoystickProvider`, `KeyboardTwistProvider`, `attach_velocity_stack`.
- Produces:
  - `factory.build_velocity_policy_components(cfg, project_root) -> tuple[Any, Any]` — public wrapper around `_build_policy_components(robot_cfg, controllers.velocity, sim_cfg, project_root, controller_cls=RLPolicyController, single_input_ok=True, propagate_defaults=False)` including the pose-B guard (`default_dof_pos` explicit) from `build_velocity_components` (factory.py:459-464).
  - `pipeline._select_cmd_provider_kind(input_provider_kind: str) -> str` — `"pico4"` → `"pico_joystick"`, else `"keyboard"`.
  - Launch: `C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_sim.py --config-name pico4_sim_velocity controller.policy_path=ckpt/track_g1.onnx`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli_entrypoints.py`, matching its existing hydra-compose style):

```python
def test_pico4_sim_velocity_config_loads_with_velocity_section():
    from hydra import compose, initialize_config_dir

    with initialize_config_dir(
        config_dir=str(PROJECT_ROOT / "teleopit" / "configs"), version_base=None
    ):
        cfg = compose(config_name="pico4_sim_velocity")
    assert str(cfg.input.provider) == "pico4"
    assert bool(cfg.keyboard.enabled) is True
    assert cfg.controllers.velocity.policy_path is not None
    assert str(cfg.command.provider) == "pico_joystick"
    assert float(cfg.safety.joint_vel_limit) == 12.0


def test_select_cmd_provider_kind_by_input():
    from teleopit.pipeline import _select_cmd_provider_kind

    assert _select_cmd_provider_kind("pico4") == "pico_joystick"
    assert _select_cmd_provider_kind("bvh") == "keyboard"
    assert _select_cmd_provider_kind("udp_bvh") == "keyboard"


def test_velocity_components_wrapper_builds_single_input_pair(monkeypatch):
    # Follows tests/test_factory_velocity.py's _FakeSession monkeypatch pattern
    # on teleopit.controllers.rl_policy._open_onnx_session with a 98D
    # single-input fake; asserts the wrapper returns (controller, obs_builder)
    # with total_obs_size == 98 and no robot-default propagation (pose B kept).
    ...
```

(The third test adapts `tests/test_factory_velocity.py`'s monkeypatch of `_open_onnx_session`; assert `obs_builder.total_obs_size == 98` and `obs_builder.default_dof_pos` equals the velocity.yaml pose B at index 3 (0.3), NOT pose A (0.669).)

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_cli_entrypoints.py -k "velocity or cmd_provider" -v`
Expected: FAIL — missing config / missing functions.

- [ ] **Step 3: Implement**

`teleopit/configs/pico4_sim_velocity.yaml`:

```yaml
# Pico 4 sim teleop WITH the twist cmd_vel VELOCITY mode (task #6).
# pico4_sim.yaml + velocity stack. keyboard.enabled=true starts STANDING:
# Y=mocap, V=velocity (only from STANDING), X=standing, A=pause/resume, B=arms, Q=quit.
# In VELOCITY: left stick = translate (Y fwd/back, X strafe), right stick X = turn.
# Joystick comes from the pico controllers (command.provider=pico_joystick);
# with bvh/udp input the keyboard twist fallback (WASD/QE) applies instead.
defaults:
  - robot: g1
  - controller: rl_policy
  - controller@controllers.velocity: velocity
  - input: pico4
  - _self_

policy_hz: 50.0
pd_hz: 200.0
keyboard:
  enabled: true
input:
  video:
    source: mujoco
retarget_buffer_enabled: true
retarget_buffer_window_s: 0.5
retarget_buffer_delay_s: null
realtime_buffer_warmup_steps: 2
reference_velocity_smoothing_alpha: 0.35
reference_anchor_velocity_smoothing_alpha: 0.25
reference_steps: [0]
reference_debug_log: false
arm_mocap:
  controlled_joint_indices: [15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28]
viewers: "all"
realtime: true
num_steps: 0

modes:
  transition_duration_s: 1.0

safety:
  joint_vel_limit: 12.0   # ratified scalar (Phase A); per-joint limits = Phase B
  tilt_threshold_rad: 1.0

command:
  provider: pico_joystick   # auto by input: pico4 -> joystick; bvh/udp -> keyboard
  joystick:
    deadzone: 0.15
    max_age_s: 0.5
  keyboard:
    speeds: {lin_x: 1.0, lin_y: 0.5, ang_z: 1.0}

hydra:
  run:
    dir: .
```

`teleopit/runtime/factory.py` — public wrapper (next to `build_velocity_components`):

```python
def build_velocity_policy_components(
    cfg: Any,
    project_root: Path,
) -> tuple[Any, Any]:
    """Build ONLY the velocity (twist_cmd) controller + obs builder pair.

    Same section resolution and pose-B guard as build_velocity_components,
    for callers that own their own robot/runner assembly (TeleopPipeline).
    """
    robot_cfg = require_section(cfg, "robot")
    controllers_cfg = cfg_get(cfg, "controllers", None)
    velocity_cfg = cfg_get(controllers_cfg, "velocity", None) if controllers_cfg is not None else None
    if velocity_cfg is None:
        raise ValueError(
            "cfg must include a 'controllers.velocity' section "
            "(policy_path, observation_type, default_dof_pos, cmd_limits, ...)."
        )
    if cfg_get(velocity_cfg, "default_dof_pos", None) is None:
        raise ValueError(
            "controllers.velocity.default_dof_pos must be set explicitly "
            "(pose B); robot defaults are pose A and must not propagate."
        )
    sim_cfg = build_simulation_cfg(cfg)
    return _build_policy_components(
        robot_cfg=robot_cfg,
        controller_cfg=velocity_cfg,
        sim_cfg=sim_cfg,
        project_root=project_root,
        controller_cls=RLPolicyController,
        single_input_ok=True,
        propagate_defaults=False,
    )
```

Also resolve velocity `policy_path` relative to project root — mirror `_prepare_policy_paths(robot_cfg, controller_cfg, project_root)` used by `_build_policy_components`; it already runs inside `_build_policy_components` (:208), so no extra work.

`teleopit/pipeline.py` — module function + attach:

```python
def _select_cmd_provider_kind(input_provider_kind: str) -> str:
    """Joystick when pico drives, keyboard otherwise (locked decision 2)."""
    return "pico_joystick" if input_provider_kind == "pico4" else "keyboard"
```

In `TeleopPipeline.__init__`, after `self.loop = SimulationLoop(...)` (:48-57):

```python
        velocity_cfg = cfg_get(cfg, "controllers.velocity", None)
        if velocity_cfg is not None:
            self._attach_velocity_stack(cfg)
```

New method:

```python
    def _attach_velocity_stack(self, cfg: Any) -> None:
        from teleopit.commands import KeyboardTwistProvider, PicoJoystickProvider
        from teleopit.runtime.factory import build_velocity_policy_components

        velocity_controller, velocity_obs_builder = build_velocity_policy_components(
            cfg, self._project_root
        )
        input_provider_kind = str(cfg_get(cfg_get(cfg, "input", {}), "provider", "bvh")).lower()
        command_cfg = cfg_get(cfg, "command", {}) or {}
        selected = str(cfg_get(command_cfg, "provider", _select_cmd_provider_kind(input_provider_kind)))
        if selected == "pico_joystick":
            joystick_cfg = cfg_get(command_cfg, "joystick", {}) or {}
            cmd_provider = PicoJoystickProvider(
                self.input_provider,
                deadzone=float(cfg_get(joystick_cfg, "deadzone", 0.15)),
                max_age_s=float(cfg_get(joystick_cfg, "max_age_s", 0.5)),
            )
        else:
            speeds = cfg_get(cfg_get(command_cfg, "keyboard", {}), "speeds", None)
            cmd_provider = KeyboardTwistProvider(speeds=speeds)  # own terminal reader
        safety_cfg = cfg_get(cfg, "safety", {}) or {}
        self.loop.attach_velocity_stack(
            velocity_controller=velocity_controller,
            velocity_obs_builder=velocity_obs_builder,
            cmd_provider=cmd_provider,
            transition_duration_s=float(
                cfg_get(cfg_get(cfg, "modes", {}), "transition_duration_s", 1.0)
            ),
            joint_vel_limit=float(cfg_get(safety_cfg, "joint_vel_limit", 12.0)),
            tilt_threshold_rad=float(cfg_get(safety_cfg, "tilt_threshold_rad", 1.0)),
            pose_b=np.asarray(velocity_obs_builder.default_dof_pos, dtype=np.float64),
        )
```

Keyboard-reader note: pico entry = one reader (session's `TerminalKeyboardReader` handles V/X/Y; joystick needs none). The bvh fallback creates a second reader inside `KeyboardTwistProvider` — acceptable because its keys (WASD/QE) are disjoint from mode keys; do NOT add a `_KeyboardTee` here (that pattern belongs to run_velocity_sim.py's single-reader constraint).

`teleopit/runtime/console.py` `sim_keyboard_controls` pico4 branch (:217-223) — add V:

```python
        return (
            KeyboardControl("Y", "mocap"),
            KeyboardControl("V", "velocity"),
            KeyboardControl("A", "pause/resume"),
            KeyboardControl("B", "arms"),
            KeyboardControl("X", "standing"),
            KeyboardControl("Q", "quit"),
        )
```

`scripts/run/run_sim.py` `_sim_status` — append a velocity row when the config has `controllers.velocity`:

```python
    velocity_cfg = cfg_get(cfg, "controllers.velocity", None)
    if velocity_cfg is not None:
        rows = rows + (("Velocity", "V from STANDING"),)
```

(structure it to fit the existing two return shapes — add the row to both after they're built.)

- [ ] **Step 4: Run tests + config smoke**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_cli_entrypoints.py tests/test_factory_velocity.py tests/test_pipeline.py -v`
Expected: all PASS.

Config composition smoke (no robot, no policy load — hydra compose only, proving defaults resolve):

```bash
cd <worktree> && C:/Users/user/.conda/envs/teleopit/python.exe -c "
from hydra import compose, initialize_config_dir
from pathlib import Path
with initialize_config_dir(config_dir=str(Path('teleopit/configs').resolve()), version_base=None):
    cfg = compose(config_name='pico4_sim_velocity')
print('policy_hz', cfg.policy_hz, '| pd_hz', cfg.pd_hz, '| cmd provider', cfg.command.provider)
print('velocity policy:', cfg.controllers.velocity.policy_path)
"
```

Expected: `policy_hz 50.0 | pd_hz 200.0 | cmd provider pico_joystick` and the repo-relative velocity policy path. Live pico/bvh smoke is deferred to the operator checklist (bridge hardware required); if a short BVH exists under `data/`, additionally run `... scripts/run/run_sim.py --config-name pico4_sim_velocity controller.policy_path=ckpt/track_g1.onnx input.provider=bvh input.bvh_file=<bvh> num_steps=50 realtime=false viewers=none` and expect a clean exit with steps=50 — check `data/` first; skip with a note if none.

- [ ] **Step 5: Commit**

```bash
git add teleopit/configs/pico4_sim_velocity.yaml teleopit/pipeline.py teleopit/runtime/factory.py teleopit/runtime/console.py scripts/run/run_sim.py tests/test_cli_entrypoints.py
git commit -m "feat(pipeline): pico sim teleop VELOCITY mode launch config"
```

---

### Task 6: Dual-entry regression + full gate + operator runbook

**Files:**
- Create: `docs/knowledge/research/2026-08-20-pico-sim-velocity-visual-check.md`
- Verification only: `tests/test_velocity_session.py`, `tests/test_velocity_integration.py`, `scripts/run/run_velocity_sim.py`

**Interfaces:**
- Consumes: everything above.
- Produces: green full-suite gate; operator HMD visual checklist doc (locked decision 6); merge + task-ledger/memory updates.

- [ ] **Step 1: Full test suite (fast)**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/ -m "not slow" -q`
Expected: 0 failures (Phase A baseline 410 passing; count grows with this plan's tests).

- [ ] **Step 2: Slow integration gate**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_velocity_integration.py -m slow -v`
Expected: 3/3 PASS (standing stability, cmd tracking, transition jump ≤ 0.25 rad).

- [ ] **Step 3: Dual-entry check — run_velocity_sim.py headless**

Run: `cd <worktree> && C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_velocity_sim.py controller.policy_path=ckpt/track_g1.onnx num_steps=50 realtime=false viewers=none`
Expected: clean exit, summary `steps=50` (headless keyboard inactive → zero cmd standing).

- [ ] **Step 4: Write the operator visual checklist**

`docs/knowledge/research/2026-08-20-pico-sim-velocity-visual-check.md` (skeleton now; results column filled after the HMD session):

```markdown
# Pico Sim VELOCITY Mode — Operator Visual Check (2026-08-20)

Launch (worktree root):
`C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_sim.py --config-name pico4_sim_velocity controller.policy_path=ckpt/track_g1.onnx`

Preconditions: Pico 4 bridge running (pico-bridge APK), operator wearing HMD,
controllers on, three viewers open, console in STANDING.

| # | Check | Expected | Result |
|---|-------|----------|--------|
| 1 | Launch | Console shows STANDING; G1 stands at pose B | |
| 2 | V (from STANDING) | Mode -> VELOCITY log; robot stays standing, no visible jump | |
| 3 | Left stick forward | Robot walks forward; speed follows stick | |
| 4 | Left stick L/R; right stick X | Strafes; turns in place | |
| 5 | Release sticks | Decelerates to standing still | |
| 6 | X | Ramps back to pose-B STANDING; heading preserved (no snap to yaw 0) | |
| 7 | Y then V | V rejected: "requires STANDING" (MOCAP direct switch forbidden) | |
| 8 | X from MOCAP, then V | Returns to STANDING; V now works | |
| 9 | Bridge disconnect mid-VELOCITY | Robot stands still (joystick zero); NO auto mode-exit | |
| 10 | Reconnect + Y | MOCAP resumes without re-warmup stall | |
| 11 | Skeleton viewer during VELOCITY | Operator skeleton keeps animating | |
| 12 | T-style tilt probe (optional) | Tilt past threshold returns STANDING | |
```

- [ ] **Step 5: Commit; merge after operator PASS**

```bash
git add docs/knowledge/research/2026-08-20-pico-sim-velocity-visual-check.md
git commit -m "docs(velocity): pico sim VELOCITY operator visual checklist"
```

After the operator confirms the checklist on hardware: merge `worktree-pico-velocity-sim` → `master` (superpowers:finishing-a-development-branch), mark task #6 completed in the task ledger, update memory `pico-teleop-velocity-task` with completion facts (launch command, measured jump on V entry, any checklist deviations).

---

## Self-Review

**Spec coverage** (6 locked decisions → tasks):
1. VELOCITY = 4th SimulationMode, bypasses mimic step, zero mocap-path changes → Task 4 (additive first branch; existing sim-loop tests stay green as the gate).
2. Joystick mapping (L: Y→lin_x, X→lin_y; R: X→ang_z; 0.15 deadzone; linear map to [-1,2]/[-0.5,0.5]/[-1,1]) + `PicoJoystickProvider` + auto-selection → Tasks 1, 2, 5.
3. V only from STANDING; X return; MOCAP→V forbidden; keyboard-only switching → Task 4 (`enter_velocity_mode` guard, keyboard routing, `test_v_rejected_from_mocap`).
4. Skeleton keeps flowing; disconnect → joystick zero, no auto exit → Task 4 (`_fetch_realtime_input_quiet`, `test_velocity_mode_survives_quiet_input_stream`) + Task 1 (stale/absent/present=False → zero tests).
5. Shared `VelocityStepController` extracted; `VelocitySimSession` + `run_velocity_sim.py` alive → Task 3 (+ Task 6 Step 3 dual-entry headless check; 22 session tests untouched).
6. pytest coverage (switch rules, joystick map/deadzone/disconnect-zero, V/X routing) + operator visual checklist → Tasks 1-5 tests + Task 6 checklist doc.

**Placeholder scan:** Task 5 Step 1's third test has a `...` body — it is a directed adaptation of an existing verified test pattern (`tests/test_factory_velocity.py` fake-session monkeypatch) with its assertions spelled out in the following note; the executor writes the body from that note. No other TBD/TODO/vague-work items. Task 3's "verbatim move" references name exact line ranges in `velocity_session.py` — the source of truth is the existing reviewed code.

**Type consistency:** `velocity_step` returns `(cmd, action, target, final_state)` — used identically in Task 3's session delegation and Task 4's `_velocity_safety_and_step`. `standing_step` returns `(standing_ref, interpolator, target, final_state)` — Task 3 session delegation unpacks 4 values. `attach_velocity_stack` keyword args match between Task 4 definition and Task 5 call. `PicoControllerState.axis_x/axis_y` names match between Tasks 1 and 2; Task 1 tolerates their absence via `getattr` default. `check_safety` string returns (`"stop"`/`"standing"`/None) match all call sites.
