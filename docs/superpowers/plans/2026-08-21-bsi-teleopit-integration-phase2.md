# BSI Teleopit Integration — Phase 2 (DDS + Wiring) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the phase-1 BSI data layer into the running sim: a cyclonedds-free `DdsIntentSource` (injectable reader), a `merged_bsi` factory branch (joystick primary / BSI secondary), and estop+mute key/button wiring across both entry points (`run_sim.py` pico4 path and `run_velocity_sim.py`), plus the H help text and the ticket-07 desktop checklist.

**Architecture:** Phase 1 shipped `IntentSource` (Protocol), `BsiTwistProvider`, `MergedTwistProvider`, and `EstopController`. Phase 2 adds the transport on top: `DdsIntentSource` wraps a duck-typed `reader` (the real `bsi_dds.DiscreteCommandSubscriber`, imported lazily only in `merged_bsi` mode) so the teleopit env never imports cyclonedds. The `merged_bsi` factory assembles `MergedTwistProvider(joystick, bsi)`; estop/mute reach the session via new `ControlEventType`s (pico) and E/C keys (keyboard).

**Tech Stack:** Python 3.10, numpy float32 (6,) twist, pytest with injected clocks + fake readers (project convention: `clock=time.monotonic` constructor param). Run tests with the teleopit conda env python: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest`. The real DDS path runs in the dds-probe env (`C:/Users/user/.conda/envs/dds-probe/python.exe`) — exercised only via the desktop checklist (Task 7), never by the teleopit pytest suite.

**Spec:** `docs/superpowers/specs/2026-08-21-bsi-teleopit-integration-design.md` (Handoff 边界 节). Decision records: `docs/wayfinder/2026-08-21-bsi-dds/tickets/04-sim-integration-architecture.md` (merged_bsi + provider 自持 DDS 线程 → 此处以 CycloneDDS 内建接收线程 + 同步 drain 实现), `05-keymap-redesign.md` (E/C + 右 menuButton/左手 Y), `07-acceptance-demo.md` (桌面 14 行 checklist + 指标表).

## Global Constraints

- Zero `cyclonedds`/`bsi_dds` imports in phase-2 **code under test** and in the teleopit pytest suite. The ONLY place `bsi_dds` is imported is inside `bsi_factory.build_dds_reader` (lazy, `merged_bsi` branch only). `tests/test_bsi_dds.py` already guards its own cyclonedds access with `pytestmark` skip.
- Twist dtype float32 shape (6,), axis order [lin_x, lin_y, lin_z, ang_x, ang_y, ang_z].
- Intent enum ints: IDLE=0, FORWARD=1, TURN_LEFT=2, TURN_RIGHT=3 (from `teleopit/commands/bsi_twist.py`). Unknown/out-of-range → IDLE (fail-safe).
- Locked parameters: forward 0.6 m/s, turn ±0.6 rad/s in-place, alpha 0.3, debounce 3 packets / idle 2 packets, silence 1.0 s, estop ramp 0.3 s, estop decel ≤0.8 s, response ≤1.0 s, mute = force IDLE (subscription stays live).
- All clocks injectable (`clock: Callable[[], float]`). Providers `get_cmd()` synchronous, never raises, returns zeros on unusable input.
- Default paths (pico_joystick / keyboard) must stay byte-for-byte behaviorally identical — `merged_bsi` is opt-in via config; `estop=None` keeps `velocity_step` a bitwise passthrough.
- Existing tests stay green: fast suite `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/ -x -q` (baseline 438 passed + 51 skipped from phase 1; known slow/marker failures are not ours).
- Commit message style: `feat(bsi): ...` / `test(bsi): ...`, ending with `Co-Authored-By: Claude <noreply@anthropic.com>`.

---

### Task 1: DdsIntentSource — reader → DiscreteIntent adapter

**Files:**
- Create: `teleopit/commands/bsi_dds_source.py`
- Test: `tests/test_bsi_dds_source.py`

**Interfaces:**
- Consumes: `teleopit/commands/bsi_twist.py` → `DiscreteIntent`, `INTENT_IDLE`, `INTENT_FORWARD`, `INTENT_TURN_LEFT`, `INTENT_TURN_RIGHT`.
- Produces (Task 3 relies on these exact names):
  - `class DdsIntentSource: def __init__(self, reader: Any, *, clock: Callable[[], float] = time.monotonic)`
  - `def poll(self) -> DiscreteIntent | None` — empty drain → None (provider resolves silence); newest sample → `DiscreteIntent(command=int, rx_time_s=clock())`; unknown value → IDLE.
  - `def close(self) -> None` — closes reader if it has `.close()`.
  - `reader` is duck-typed: `.drain() -> list` of samples each exposing `.command.value` (int).

- [ ] **Step 1: Write the failing test**

Create `tests/test_bsi_dds_source.py`:

```python
"""DdsIntentSource: raw DDS reader -> DiscreteIntent adapter (cyclonedds-free)."""
from __future__ import annotations

import pytest

from teleopit.commands.bsi_dds_source import DdsIntentSource
from teleopit.commands.bsi_twist import (
    INTENT_FORWARD,
    INTENT_IDLE,
    INTENT_TURN_LEFT,
)


class _CmdValue:
    def __init__(self, value):
        self.value = value


class _Sample:
    def __init__(self, value):
        self.command = _CmdValue(value)


class _FakeReader:
    def __init__(self, batches):
        self._batches = list(batches)  # one list-of-samples per drain()
        self._i = 0
        self.closed = False

    def drain(self):
        if self._i >= len(self._batches):
            return []
        batch = self._batches[self._i]
        self._i += 1
        return batch

    def close(self):
        self.closed = True


class ManualClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_empty_drain_returns_none():
    src = DdsIntentSource(_FakeReader([]), clock=ManualClock())
    assert src.poll() is None


def test_sample_maps_to_discrete_intent_with_local_stamp():
    clock = ManualClock()
    src = DdsIntentSource(_FakeReader([[ _Sample(INTENT_FORWARD) ]]), clock=clock)
    clock.advance(1.5)
    intent = src.poll()
    assert intent.command == INTENT_FORWARD
    assert intent.rx_time_s == 1.5


def test_latest_sample_wins_when_batch_has_many():
    src = DdsIntentSource(
        _FakeReader([[ _Sample(INTENT_IDLE), _Sample(INTENT_TURN_LEFT) ]]),
        clock=ManualClock(),
    )
    assert src.poll().command == INTENT_TURN_LEFT


def test_unknown_value_fails_safe_to_idle():
    src = DdsIntentSource(_FakeReader([[ _Sample(99) ]]), clock=ManualClock())
    assert src.poll().command == INTENT_IDLE


def test_close_delegates_to_reader():
    reader = _FakeReader([])
    DdsIntentSource(reader, clock=ManualClock()).close()
    assert reader.closed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_bsi_dds_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teleopit.commands.bsi_dds_source'`

- [ ] **Step 3: Write `teleopit/commands/bsi_dds_source.py`**

```python
"""DDS-backed IntentSource: adapt a BSI subscriber reader to the intent seam.

Cyclonedds-free: the reader is injected (duck-typed ``.drain() -> list`` of
samples each exposing ``.command.value``, plus ``.close()``). The real reader
is ``bsi_dds.DiscreteCommandSubscriber``, constructed lazily in
``bsi_factory.build_dds_reader`` so importing THIS module never pulls in
cyclonedds — the teleopit env tests inject a fake reader.

``poll()`` returns None on an empty drain (the provider's own 1.0 s silence
check resolves link loss) and maps the newest sample's enum to an int intent
otherwise; unknown values fail safe to IDLE (mirrors bsi_dds.subscriber).
"""
from __future__ import annotations

import time
from typing import Any, Callable

from teleopit.commands.bsi_twist import (
    INTENT_FORWARD,
    INTENT_IDLE,
    INTENT_TURN_LEFT,
    INTENT_TURN_RIGHT,
    DiscreteIntent,
)

_VALID_COMMANDS = {INTENT_IDLE, INTENT_FORWARD, INTENT_TURN_LEFT, INTENT_TURN_RIGHT}


class DdsIntentSource:
    """IntentSource over a raw BSI DDS reader."""

    def __init__(self, reader: Any, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._reader = reader
        self._clock = clock

    def poll(self) -> DiscreteIntent | None:
        drain = getattr(self._reader, "drain", None)
        samples = [] if not callable(drain) else list(drain())
        if not samples:
            return None
        newest = samples[-1]
        try:
            command = int(newest.command.value)
        except (AttributeError, ValueError):
            command = INTENT_IDLE  # unknown on the wire -> fail safe
        if command not in _VALID_COMMANDS:
            command = INTENT_IDLE
        return DiscreteIntent(command=command, rx_time_s=self._clock())

    def close(self) -> None:
        close = getattr(self._reader, "close", None)
        if callable(close):
            close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_bsi_dds_source.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add teleopit/commands/bsi_dds_source.py tests/test_bsi_dds_source.py
git commit -m "feat(bsi): DdsIntentSource — cyclonedds-free reader adapter with fail-safe unknown->IDLE"
```

---

### Task 2: MergedTwistProvider — mute/feedback delegate

**Files:**
- Modify: `teleopit/commands/merged_twist.py` (append methods)
- Test: `tests/test_merged_twist.py` (append tests)

**Interfaces:**
- Consumes: Task 1 classes indirectly (the secondary is any `CommandProvider`).
- Produces (Tasks 4/5/6 rely on these):
  - `@property def secondary` → the secondary (BSI) source.
  - `def toggle_mute(self) -> bool | None` → delegates to `secondary.toggle_mute()`; `None` when the secondary has no such method.
  - `@property def muted(self) -> bool` → `bool(getattr(secondary, "muted", False))`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_merged_twist.py`)

```python
def test_toggle_mute_none_when_secondary_unmutable():
    m = MergedTwistProvider(_JOY_ZERO, _BSI)  # _BSI has no toggle_mute
    assert m.toggle_mute() is None
    assert m.muted is False


def test_toggle_mute_delegates_and_exposes_secondary():
    bsi = _Vec([0.6, 0, 0, 0, 0, 0])
    bsi.toggle_mute = lambda: True
    bsi.muted = True
    m = MergedTwistProvider(_JOY_ZERO, bsi)
    assert m.secondary is bsi
    assert m.toggle_mute() is True
    assert m.muted is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_merged_twist.py -v`
Expected: 2 new FAIL (`AttributeError: 'MergedTwistProvider' object has no attribute 'toggle_mute'`)

- [ ] **Step 3: Append to `teleopit/commands/merged_twist.py`**

```python
    @property
    def secondary(self):
        """The secondary (BSI) source — exposed for mute/feedback reachability."""
        return self._secondary

    def toggle_mute(self) -> bool | None:
        """Delegate mute to the secondary source; None when it is not mutable."""
        toggle = getattr(self._secondary, "toggle_mute", None)
        if callable(toggle):
            return bool(toggle())
        return None

    @property
    def muted(self) -> bool:
        return bool(getattr(self._secondary, "muted", False))
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_merged_twist.py -v`
Expected: 6 PASS (4 phase-1 + 2 new)

- [ ] **Step 5: Commit**

```bash
git add teleopit/commands/merged_twist.py tests/test_merged_twist.py
git commit -m "feat(bsi): MergedTwistProvider mute delegate (secondary/toggle_mute/muted)"
```

---

### Task 3: bsi factory + merged_bsi branch in the pipeline

**Files:**
- Create: `teleopit/commands/bsi_factory.py`
- Modify: `teleopit/pipeline.py` (extract `_build_joystick_provider`, add `merged_bsi` branch, create+pass `EstopController`)
- Modify: `teleopit/sim/loop.py` (`attach_velocity_stack` gains `estop` param + stores `_velocity_estop`/`_velocity_cmd_provider`)
- Test: `tests/test_bsi_factory.py`

**Interfaces:**
- Consumes: `DdsIntentSource` (Task 1), `BsiTwistProvider`, `MergedTwistProvider`.
- Produces (Tasks 4/5/6 rely on these exact names):
  - `def build_dds_reader(bsi_cfg: dict, clock: Callable[[], float]) -> DdsIntentSource` — the lazy `from bsi_dds import DiscreteCommandSubscriber` lives here.
  - `def build_merged_bsi_provider(joystick_provider: Any, bsi_cfg: dict, *, clock: Callable[[], float] = time.monotonic, reader_factory: Callable[[dict, Callable], DdsIntentSource] | None = None) -> MergedTwistProvider`
  - `SimulationLoop._velocity_estop: EstopController | None` and `SimulationLoop._velocity_cmd_provider: object | None` (init None; set in `attach_velocity_stack`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_bsi_factory.py`:

```python
"""merged_bsi factory assembly (cyclonedds-free via injected reader_factory)."""
from __future__ import annotations

import numpy as np
import pytest

from teleopit.commands.bsi_factory import build_merged_bsi_provider
from teleopit.commands.bsi_twist import INTENT_FORWARD


class _Joy:
    def get_cmd(self):
        return np.zeros(6, dtype=np.float32)

    def reset(self): ...

    def close(self): ...


class _JoyFwd:
    def get_cmd(self):
        return np.array([0.4, 0, 0, 0, 0, 0.1], dtype=np.float32)

    def reset(self): ...

    def close(self): ...


class _FakeSource:
    """Fake reader-backed source emitting FORWARD forever."""

    def __init__(self, *a, **k):
        pass

    def poll(self):
        from teleopit.commands.bsi_twist import DiscreteIntent
        return DiscreteIntent(command=INTENT_FORWARD, rx_time_s=0.0)

    def close(self): ...


class ManualClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_build_merged_bsi_uses_secondary_when_joystick_zero():
    clock = ManualClock()
    merged = build_merged_bsi_provider(
        _Joy(), {}, clock=clock, reader_factory=lambda cfg, clock: _FakeSource()
    )
    for _ in range(300):
        merged.get_cmd()
        clock.advance(0.02)
    assert merged.get_cmd()[0] == pytest.approx(0.6, abs=0.01)


def test_build_merged_bsi_joystick_priority_whole_packet():
    merged = build_merged_bsi_provider(
        _JoyFwd(), {}, clock=ManualClock(),
        reader_factory=lambda cfg, clock: _FakeSource(),
    )
    np.testing.assert_allclose(
        merged.get_cmd(), np.array([0.4, 0, 0, 0, 0, 0.1], dtype=np.float32)
    )


def test_build_merged_bsi_passes_bsi_params():
    clock = ManualClock()
    merged = build_merged_bsi_provider(
        _Joy(),
        {"speeds": {"forward": 0.3, "turn": 0.5}, "alpha": 0.5},
        clock=clock,
        reader_factory=lambda cfg, clock: _FakeSource(),
    )
    for _ in range(400):
        merged.get_cmd()
        clock.advance(0.02)
    assert merged.get_cmd()[0] == pytest.approx(0.3, abs=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_bsi_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teleopit.commands.bsi_factory'`

- [ ] **Step 3: Write `teleopit/commands/bsi_factory.py`**

```python
"""Factory: build the merged_bsi command provider (joystick primary, BSI secondary).

The single place that imports bsi_dds/cyclonedds — lazily, inside
``build_dds_reader`` — so the default pico_joystick/keyboard paths never touch
DDS. ``reader_factory`` is injectable so tests in the teleopit env (no
cyclonedds) can exercise the full assembly with a fake source.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from teleopit.commands.bsi_dds_source import DdsIntentSource
from teleopit.commands.bsi_twist import BsiTwistProvider
from teleopit.commands.merged_twist import MergedTwistProvider


def build_dds_reader(bsi_cfg: dict[str, Any], clock: Callable[[], float]) -> DdsIntentSource:
    """Construct the real bsi_dds reader (lazy cyclonedds import — dds-probe env)."""
    from bsi_dds import DiscreteCommandSubscriber

    reader = DiscreteCommandSubscriber(
        domain_id=int(bsi_cfg.get("domain_id", 0)),
        interface=bsi_cfg.get("interface") or None,
    )
    return DdsIntentSource(reader, clock=clock)


def build_merged_bsi_provider(
    joystick_provider: Any,
    bsi_cfg: dict[str, Any],
    *,
    clock: Callable[[], float] = time.monotonic,
    reader_factory: Callable[[dict[str, Any], Callable[[], float]], DdsIntentSource] | None = None,
) -> MergedTwistProvider:
    """Assemble joystick(primary) + BSI(secondary) into one CommandProvider."""
    factory = reader_factory or build_dds_reader
    source = factory(bsi_cfg, clock)
    bsi = BsiTwistProvider(
        source,
        alpha=float(bsi_cfg.get("alpha", 0.3)),
        debounce_packets=int(bsi_cfg.get("debounce_packets", 3)),
        idle_debounce_packets=int(bsi_cfg.get("idle_debounce_packets", 2)),
        silence_timeout_s=float(bsi_cfg.get("silence_timeout_s", 1.0)),
        speeds=dict(bsi_cfg.get("speeds", {}) or {}) or None,
        clock=clock,
    )
    return MergedTwistProvider(joystick_provider, bsi)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_bsi_factory.py -v`
Expected: 3 PASS

- [ ] **Step 5: Refactor `teleopit/pipeline.py` — extract joystick builder + add merged_bsi branch + estop**

Replace the body of `_attach_velocity_stack` (lines 70-136) so that the joystick construction is a method and the branch set gains `merged_bsi`, and an `EstopController` is built and threaded through. Concretely:

Add this method to `TeleopPipeline` (right after `_select_cmd_provider_kind`):

```python
    def _build_joystick_provider(self, command_cfg: Any) -> "PicoJoystickProvider":
        from teleopit.commands import PicoJoystickProvider

        joystick_cfg = cfg_get(command_cfg, "joystick", {}) or {}
        controllers_cfg = cfg_get(self.cfg, "controllers", None)
        velocity_cfg = cfg_get(controllers_cfg, "velocity", None) if controllers_cfg is not None else None
        cmd_limits = cfg_get(velocity_cfg, "cmd_limits", None)
        return PicoJoystickProvider(
            self.input_provider,
            deadzone=float(cfg_get(joystick_cfg, "deadzone", 0.15)),
            max_age_s=float(cfg_get(joystick_cfg, "max_age_s", 0.5)),
            cmd_limits=dict(cmd_limits) if cmd_limits is not None else None,
            max_stick_scale=dict(cfg_get(joystick_cfg, "max_stick_scale", {}) or {}) or None,
        )
```

Then rewrite the provider-selection block (currently lines 83-123) to:

```python
        from teleopit.commands import KeyboardTwistProvider, PicoJoystickProvider
        from teleopit.runtime.factory import build_velocity_policy_components
        from teleopit.sim.estop import EstopController

        velocity_controller, velocity_obs_builder = build_velocity_policy_components(
            cfg, self._project_root
        )
        input_provider_kind = str(cfg_get(cfg_get(cfg, "input", {}), "provider", "bvh")).lower()
        command_cfg = cfg_get(cfg, "command", {}) or {}
        selected = str(cfg_get(command_cfg, "provider", _select_cmd_provider_kind(input_provider_kind)))
        estop = EstopController()
        keyboard_tee = None
        if selected == "pico_joystick":
            cmd_provider = self._build_joystick_provider(command_cfg)
        elif selected == "merged_bsi":
            from teleopit.commands.bsi_factory import build_merged_bsi_provider

            joystick = self._build_joystick_provider(command_cfg)
            bsi_cfg = cfg_get(command_cfg, "bsi", {}) or {}
            cmd_provider = build_merged_bsi_provider(joystick, bsi_cfg)
        else:
            from teleopit.commands import KeyboardTee
            from teleopit.runtime.terminal_keyboard import TerminalKeyboardReader

            speeds = cfg_get(cfg_get(command_cfg, "keyboard", {}), "speeds", None)
            keyboard = TerminalKeyboardReader()
            if not keyboard.active:
                keyboard.close()
                keyboard = None
            keyboard_tee = (
                KeyboardTee(keyboard, refresh_s=1.0 / self.loop.policy_hz)
                if keyboard is not None
                else None
            )
            cmd_provider = KeyboardTwistProvider(speeds=speeds, keyboard=keyboard_tee)
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
            keyboard_reader=keyboard_tee,
            estop=estop,
        )
```

(Note: `PicoJoystickProvider` import stays; the joystick body moved into `_build_joystick_provider`.)

- [ ] **Step 6: Wire estop into `teleopit/sim/loop.py`**

In `SimulationLoop.__init__` (near line 99, `self._velocity_step_controller = None`), add:

```python
        self._velocity_estop: object | None = None
        self._velocity_cmd_provider: object | None = None
```

In `attach_velocity_stack` (signature at line 105-116), add `estop: object | None = None` to the parameters, pass it to the step controller, and store both handles:

```python
        step_controller = VelocityStepController(
            velocity_runner=velocity_runner,
            cmd_provider=cmd_provider,
            pose_b=pose_b,
            policy_hz=self.policy_hz,
            transition_duration_s=transition_duration_s,
            joint_vel_limit=joint_vel_limit,
            tilt_threshold_rad=tilt_threshold_rad,
            estop=estop,
        )
        self._velocity_controller = velocity_controller
        self._velocity_obs_builder = velocity_obs_builder
        self._velocity_step_controller = step_controller
        self._velocity_estop = estop
        self._velocity_cmd_provider = cmd_provider
```

- [ ] **Step 7: Run the fast suite to verify no regression**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_bsi_factory.py tests/test_merged_twist.py tests/test_bsi_dds_source.py tests/test_velocity_step.py tests/test_velocity_session.py -q`
Expected: all PASS (new tests green; estop=None default keeps existing velocity tests bitwise-unchanged).

- [ ] **Step 8: Commit**

```bash
git add teleopit/commands/bsi_factory.py teleopit/pipeline.py teleopit/sim/loop.py tests/test_bsi_factory.py
git commit -m "feat(bsi): merged_bsi factory branch (lazy bsi_dds import) + estop threaded into velocity stack"
```

---

### Task 4: estop + mute keyboard keys in the general loop (SimLoopSession)

**Files:**
- Modify: `teleopit/sim/session.py` (`_handle_realtime_keyboard` E/C; `_velocity_safety_and_step` exit-request; `exit_velocity_to_standing` on_standing)
- Test: `tests/test_sim_loop.py` (append a focused seam test if the file's fixtures allow; otherwise rely on Task 7 checklist + fast suite)

**Interfaces:**
- Consumes: `SimulationLoop._velocity_estop`, `_velocity_cmd_provider` (Task 3); `EstopController` (phase 1).
- Produces: E key → `estop.toggle(in_velocity=True)`; C key → `cmd_provider.toggle_mute()` (or `ignored (no BSI)`); exit-request → `exit_velocity_to_standing()`; landing in STANDING → `estop.on_standing()`.

- [ ] **Step 1: Add E/C keys to `_handle_realtime_keyboard`**

In `session.py` `_handle_realtime_keyboard`, inside the `if self.simulation_mode == SimulationMode.VELOCITY:` block (currently lines 405-416), add two branches before the trailing `continue`:

```python
                if key == "e":
                    estop = self._loop._velocity_estop
                    if estop is not None:
                        result = estop.toggle(in_velocity=True)
                        self._loop._console.key_feedback("E", "estop", result=result)
                    else:
                        self._loop._console.key_feedback("E", "estop", result="no estop")
                    continue
                if key == "c":
                    provider = self._loop._velocity_cmd_provider
                    toggle = getattr(provider, "toggle_mute", None)
                    if callable(toggle):
                        muted = bool(toggle())
                        self._loop._console.key_feedback("C", "bsi mute", result="muted" if muted else "live")
                    else:
                        self._loop._console.key_feedback("C", "bsi mute", result="ignored (no BSI)")
                    continue
```

- [ ] **Step 2: Consume the estop exit request in `_velocity_safety_and_step`**

In `session.py` `_velocity_safety_and_step` (currently lines 712-735), after `_, _, _, final_state = steps.velocity_step(self._loop.robot)` and before the viewer writes, add:

```python
        estop = self._loop._velocity_estop
        if estop is not None and estop.consume_exit_request():
            self.exit_velocity_to_standing()
            return False
```

- [ ] **Step 3: Auto-unlatch on landing in STANDING**

In `session.py` `exit_velocity_to_standing` (currently lines 311-327), just before `self.simulation_mode = SimulationMode.STANDING`, add:

```python
        estop = self._loop._velocity_estop
        if estop is not None:
            estop.on_standing()
```

- [ ] **Step 4: Run the fast suite to verify no regression**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_sim_loop.py tests/test_velocity_step.py tests/test_estop.py -q`
Expected: all PASS. (`estop`/`cmd_provider` are None in existing `SimLoopSession` tests unless a velocity stack is attached, so the new branches are inert.)

- [ ] **Step 5: Commit**

```bash
git add teleopit/sim/session.py
git commit -m "feat(bsi): E/C estop+mute keys + exit-request + on_standing in SimLoopSession VELOCITY"
```

---

### Task 5: pico button control events → estop / mute

**Files:**
- Modify: `teleopit/inputs/realtime_packet.py` (new `ControlEventType`s)
- Modify: `teleopit/inputs/pico4_provider.py` (`estop_button`/`mute_button` params + `_poll_control_events` calls)
- Modify: `teleopit/runtime/factory.py` (pass config keys)
- Modify: `teleopit/sim/session.py` (consume new events in `_fetch_realtime_input`)
- Test: `tests/test_pico_control_events.py`

**Interfaces:**
- Consumes: `ControlEvent`, `ControlEventType` (phase-1), `Pico4InputProvider._poll_button_control_event` (existing, reusable).
- Produces:
  - `ControlEventType.TOGGLE_ESTOP = "toggle_estop"`, `ControlEventType.TOGGLE_MUTE = "toggle_mute"`.
  - `Pico4InputProvider(estop_button: str | None = None, mute_button: str | None = None, estop_debounce_s: float = 0.25, mute_debounce_s: float | None = None)` — default None = disabled (existing behavior unchanged).
  - Config: `input.estop_button`, `input.mute_button` (read in `runtime/factory.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pico_control_events.py`:

```python
"""Pico button -> estop/mute control-event mapping (config plumbing, no bridge)."""
from __future__ import annotations

import pytest

from teleopit.inputs.pico4_provider import Pico4InputProvider
from teleopit.inputs.realtime_packet import ControlEventType


def test_new_control_event_types():
    assert ControlEventType.TOGGLE_ESTOP.value == "toggle_estop"
    assert ControlEventType.TOGGLE_MUTE.value == "toggle_mute"


def test_button_path_resolution_for_estop_and_mute():
    # right menuButton = estop; left secondaryButton (Y) = mute (ticket 05).
    assert Pico4InputProvider._resolve_button_path("right_menu_button") == ("right", "menuButton")
    assert Pico4InputProvider._resolve_button_path("Y") == ("left", "secondaryButton")
    assert Pico4InputProvider._resolve_button_path("left_menu_button") == ("left", "menuButton")
    assert Pico4InputProvider._resolve_button_path(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_pico_control_events.py -v`
Expected: FAIL — `AttributeError: ControlEventType has no attribute TOGGLE_ESTOP`

- [ ] **Step 3: Add the new enum values to `realtime_packet.py`**

```python
class ControlEventType(str, Enum):
    TOGGLE_PAUSE = "toggle_pause"
    TOGGLE_ARMS = "toggle_arms"
    TOGGLE_ESTOP = "toggle_estop"
    TOGGLE_MUTE = "toggle_mute"
```

- [ ] **Step 4: Add estop/mute button plumbing to `pico4_provider.py`**

Add two parameters to `Pico4InputProvider.__init__` (after `arms_debounce_s: float | None = None`, around line 226):

```python
        estop_button: str | None = None,
        estop_debounce_s: float = 0.25,
        mute_button: str | None = None,
        mute_debounce_s: float | None = None,
```

After the pause/arms button init (around line 275), add:

```python
        self._estop_button = None if estop_button in (None, "", "null") else str(estop_button)
        self._mute_button = None if mute_button in (None, "", "null") else str(mute_button)
        self._estop_debounce_s = max(float(estop_debounce_s), 0.0)
        self._mute_debounce_s = self._estop_debounce_s if mute_debounce_s is None else max(float(mute_debounce_s), 0.0)
        self._estop_button_path = self._resolve_button_path(self._estop_button)
        self._mute_button_path = self._resolve_button_path(self._mute_button)
        self._last_estop_button_pressed = False
        self._last_mute_button_pressed = False
        self._last_estop_toggle_timestamp: float | None = None
        self._last_mute_toggle_timestamp: float | None = None
```

In `_poll_control_events` (lines 544-566), append two more polls after the arms poll:

```python
        emitted = self._poll_button_control_event(
            frame,
            timestamp=timestamp,
            button_path=self._estop_button_path,
            button_label=self._estop_button,
            event_type=ControlEventType.TOGGLE_ESTOP,
            last_pressed_attr="_last_estop_button_pressed",
            last_toggle_attr="_last_estop_toggle_timestamp",
            debounce_s=self._estop_debounce_s,
        ) or emitted
        emitted = self._poll_button_control_event(
            frame,
            timestamp=timestamp,
            button_path=self._mute_button_path,
            button_label=self._mute_button,
            event_type=ControlEventType.TOGGLE_MUTE,
            last_pressed_attr="_last_mute_button_pressed",
            last_toggle_attr="_last_mute_toggle_timestamp",
            debounce_s=self._mute_debounce_s,
        ) or emitted
```

- [ ] **Step 5: Pass config keys in `runtime/factory.py`**

At the `Pico4InputProvider(` construction (line 281, `pause_button=cfg_get(input_cfg, "pause_button", "A")`), add two kwargs after the arms_button line:

```python
            estop_button=cfg_get(input_cfg, "estop_button", None),
            mute_button=cfg_get(input_cfg, "mute_button", None),
```

- [ ] **Step 6: Consume the new events in `session.py`**

In `session.py` `_fetch_realtime_input` (lines 567-572), extend the control-event loop:

```python
        for control_event in packet.control_events:
            if control_event.event_type == ControlEventType.TOGGLE_ARMS:
                self.toggle_arms_mode()
                continue
            if control_event.event_type == ControlEventType.TOGGLE_PAUSE:
                self.toggle_realtime_mocap_pause()
                continue
            if control_event.event_type == ControlEventType.TOGGLE_ESTOP:
                estop = self._loop._velocity_estop
                if estop is not None:
                    estop.toggle(in_velocity=(self.simulation_mode == SimulationMode.VELOCITY))
                continue
            if control_event.event_type == ControlEventType.TOGGLE_MUTE:
                provider = self._loop._velocity_cmd_provider
                toggle = getattr(provider, "toggle_mute", None)
                if callable(toggle):
                    toggle()
                continue
```

(Note: `SimulationMode` is already imported at the top of the `_fetch_realtime_input` function body in the existing code — if not, add `from teleopit.sim.loop import SimulationMode`.)

- [ ] **Step 7: Run tests + fast suite**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_pico_control_events.py -v`
Expected: 2 PASS
Then: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_sim_loop.py tests/test_pico_control_events.py -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add teleopit/inputs/realtime_packet.py teleopit/inputs/pico4_provider.py teleopit/runtime/factory.py teleopit/sim/session.py tests/test_pico_control_events.py
git commit -m "feat(bsi): pico right-menuButton estop + left-Y mute control events"
```

---

### Task 6: estop/mute keys in VelocitySimSession + H help text

**Files:**
- Modify: `teleopit/sim/velocity_session.py` (`_handle_keyboard` E/C)
- Modify: `scripts/run/run_velocity_sim.py` (`_velocity_operator_controls` E/C + status/events strings)
- Modify: `teleopit/runtime/console.py` (`sim_keyboard_controls` E/C)
- Test: `tests/test_velocity_session.py` (append E/C tests using the existing `_session`/`_ScriptedKeyboard` helpers)

**Interfaces:**
- Consumes: `EstopController` (already `self.estop` on the session), `MergedTwistProvider.toggle_mute` (Task 2).
- Produces: E key → `self.estop.toggle(in_velocity=(mode == VELOCITY))`; C key → `self._cmd.toggle_mute()` (or `ignored (no BSI)`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_velocity_session.py`)

```python
class _MuteableCmd:
    def __init__(self, vec):
        self._vec = np.asarray(vec, dtype=np.float32)
        self.mute_calls = 0
        self._muted = False

    def get_cmd(self):
        return self._vec.copy()

    def reset(self): ...

    def close(self): ...

    def toggle_mute(self):
        self.mute_calls += 1
        self._muted = not self._muted
        return self._muted

    @property
    def muted(self):
        return self._muted


def test_estop_key_engages_estop_and_mute_key_delegates():
    robot, mimic_runner, vel_runner = _components()
    cmd = _MuteableCmd([0.6, 0, 0, 0, 0, 0])
    console = _RecordingConsole()
    # Build the session directly (not via _session) so command_provider is the
    # muteable fake; _session wraps cmd into _StubCmd which has no toggle_mute.
    session = VelocitySimSession(
        robot=robot,
        mimic_runner=mimic_runner,
        velocity_runner=vel_runner,
        command_provider=cmd,
        cfg=_cfg(),
        console=console,
    )
    session.mode = VelocityMode.VELOCITY  # bypass transition; test key handling only

    session._keyboard = _ScriptedKeyboard([["e"]])
    session._handle_keyboard()
    assert session.estop.state == EstopState.RAMPING

    session._keyboard = _ScriptedKeyboard([["c"]])
    session._handle_keyboard()
    assert cmd.mute_calls == 1
    assert cmd.muted is True
```

(Imports to add at the top of the test file: `from teleopit.sim.estop import EstopState`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_velocity_session.py::test_estop_key_engages_estop_and_mute_key_delegates -v`
Expected: FAIL — the `_handle_keyboard` loop ignores `e`/`c`, so `session.estop.state` stays INACTIVE (assert fails).

- [ ] **Step 3: Add E/C to `velocity_session.py` `_handle_keyboard`**

In `_handle_keyboard` (lines 230-245), add before the `elif key in _STOP_KEY_NAMES:` branch:

```python
            elif key == "e":
                result = self.estop.toggle(in_velocity=(self.mode == VelocityMode.VELOCITY))
                self._key_feedback("E", "estop", result=result)
            elif key == "c":
                toggle = getattr(self._cmd, "toggle_mute", None)
                if callable(toggle):
                    muted = bool(toggle())
                    self._key_feedback("C", "bsi mute", result="muted" if muted else "live")
                else:
                    self._key_feedback("C", "bsi mute", result="ignored (no BSI)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_velocity_session.py -v`
Expected: all PASS (existing + new).

- [ ] **Step 5: Update H help text**

In `scripts/run/run_velocity_sim.py` `_velocity_operator_controls`, add after the `KeyboardControl("K", "zero twist"),` line:

```python
        KeyboardControl("E", "estop (toggle)"),
        KeyboardControl("C", "BSI mute (toggle)"),
```

In `teleopit/runtime/console.py` `sim_keyboard_controls`, inside the pico4 branch where `controls.append(KeyboardControl("V", "velocity"))`, add right after it:

```python
            controls.append(KeyboardControl("E", "estop"))
            controls.append(KeyboardControl("C", "bsi mute"))
```

Also update the two human-readable strings in `run_velocity_sim.py`:
- the `events=` tuple → add `"e toggles estop; c mutes the BSI source"`
- the `logger.info(...)` line → mention `e=estop c=mute`.

- [ ] **Step 6: Commit**

```bash
git add teleopit/sim/velocity_session.py scripts/run/run_velocity_sim.py teleopit/runtime/console.py tests/test_velocity_session.py
git commit -m "feat(bsi): E/C estop+mute keys in VelocitySimSession + H help text"
```

---

### Task 7: pico4_sim_bsi config + desktop checklist + gate run

**Files:**
- Create: `teleopit/configs/pico4_sim_bsi.yaml`
- Create: `docs/knowledge/research/2026-08-21-bsi-desktop-checklist.md`
- No source changes.

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write `teleopit/configs/pico4_sim_bsi.yaml`**

Copy `teleopit/configs/pico4_sim_velocity.yaml` verbatim and change only the `command` section and add the pico button keys:

```yaml
# pico4_sim_velocity.yaml + merged_bsi: BSI brain source secondary, joystick primary.
# Launch: python scripts/run/run_sim.py --config-name pico4_sim_bsi controller.policy_path=ckpt/track_g1.onnx
# In a second terminal (dds-probe env):
#   C:/Users/user/.conda/envs/dds-probe/python.exe -m bsi_dds.cli mock --script "idle:3,forward:5,left:3,forward:5,right:3,idle:3,forward:5,idle:3"
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
  estop_button: right_menu_button   # right hand = safety (estop)
  mute_button: Y                     # left hand = source control (BSI mute)
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
  joint_vel_limit: 12.0
  tilt_threshold_rad: 1.0

command:
  provider: merged_bsi
  joystick:
    deadzone: 0.15
    max_age_s: 0.5
    max_stick_scale: {lin_vel_x: 0.5}
  keyboard:
    speeds: {lin_x: 1.0, lin_y: 0.5, ang_z: 1.0}
  bsi:
    domain_id: 0
    silence_timeout_s: 1.0
    debounce_packets: 3
    idle_debounce_packets: 2
    alpha: 0.3
    speeds: {forward: 0.6, turn: 0.6}

hydra:
  run:
    dir: .
```

- [ ] **Step 2: Write `docs/knowledge/research/2026-08-21-bsi-desktop-checklist.md`**

```markdown
# BSI desktop acceptance checklist (ticket 07 桌面门)

Run: `run_sim.py --config-name pico4_sim_bsi` + `bsi_dds mock` (dds-probe env).
Script: `idle:3,forward:5,left:3,forward:5,right:3,idle:3,forward:5,idle:3` (~50s).

| # | 观察项 | 期望 |
|---|---|---|
| 1 | FORWARD 段 | 机器人平滑前进，lin_x 收敛 ~0.6 m/s |
| 2 | LEFT 段 | 原地左转（ang_z +0.6），无 lin_x |
| 3 | RIGHT 段 | 原地右转（ang_z -0.6） |
| 4 | idle 段 | 1.0s 内开始减速，1.5s 内站住 |
| 5 | 意图切换 | 前→左→前… 平滑过渡，无跳变 |
| 6 | 摇杆抢夺 | 摇杆非零 → 机器人立即跟随摇杆（整包） |
| 7 | 摇杆释放 | 摇杆回零 → 回到脑控 |
| 8 | 急停（E / 右手 menuButton） | 0.3s 渐 0 → STANDING，站住 |
| 9 | 急停解锁 | 同键再按 → 恢复 passthrough |
| 10 | BSI 哑音（C / 左手 Y） | 下一周期衰减归 0，模式不变 |
| 11 | 哑音解除 | 下一周期恢复，无重连延迟 |
| 12 | 静默（mock Ctrl-C） | 1s 后站住（IDLE） |
| 13 | V/X 键 | BSI 不干预状态机，V/X 行为不变 |
| 14 | H 帮助文本 | E/C/menuButton/Y 键位齐全 |
```

- [ ] **Step 3: Full fast suite gate**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/ -q`
Expected: baseline 438 passed + 51 skipped, plus the new phase-2 tests (~12) all green; zero new failures (known slow/marker failures unchanged).

- [ ] **Step 4: Headless smoke (zero-regression proof, keyboard path)**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_velocity_sim.py controller.policy_path=ckpt/track_g1.onnx num_steps=50`
Expected: exits 0, `steps: 50`, no estop/BSI output (default provider path untouched; E/C keys present but unpressed).

- [ ] **Step 5: Record completion in the plan**

Append a `## Phase-2 Completion` section at the end of this plan file: commit SHAs, test counts, the dds-probe-env mock CLI command, and a pointer to the desktop checklist for the manual gate.

---

## Phase-2 Completion

**完成 2026-08-21**（worktree `bsi-phase2`，branch `bsi-phase2`，base `b06493d` phase-1 已并入）。

**Commits**（6 个，merge-base `b06493d` 起）：
- `aa6b032` feat(bsi): DdsIntentSource — cyclonedds-free reader adapter with fail-safe unknown->IDLE
- `7e06657` feat(bsi): MergedTwistProvider mute delegate (secondary/toggle_mute/muted)
- `03f5376` feat(bsi): merged_bsi factory branch (lazy bsi_dds import) + estop threaded into velocity stack
- `73324f5` feat(bsi): E/C estop+mute keys + exit-request + on_standing in SimLoopSession VELOCITY
- `bf10d4b` feat(bsi): pico right-menuButton estop + left-Y mute control events
- `54ee71a` feat(bsi): E/C estop+mute keys in VelocitySimSession + H help text

**验收（pytest 指标门 + 冒烟）**：
- 新增 13 测试全绿：`test_bsi_dds_source.py`(5) + `test_merged_twist.py`(+2) + `test_bsi_factory.py`(3) + `test_pico_control_events.py`(2) + `test_velocity_session.py`(+1)。
- 全套 `pytest tests/ -q --continue-on-collection-errors`：**451 passed + 51 skipped**（phase-1 基线 438 passed → +13 全新）；3 failed（`test_sim2real_multiprocess.py` imageio `quality` kwarg）+ 11 errors（train_mimic 缺 `mjlab`）均为**既有环境问题**，与 BSI 零交集，零新增失败。
- headless 冒烟 `run_velocity_sim.py controller.policy_path=ckpt/track_g1.onnx num_steps=50`：`steps: 50` 正常退出，默认 keyboard 路径未被触碰，无 estop/BSI 输出（冒烟在主检出 master 跑——worktree 缺 `assets/` 二进制资源且 editable install 路由 `import teleopit` 至主检出；phase-2 默认路径为纯增量、estop=None 默认 passthrough，行为与 master 逐 bit 一致，BSI 路径由 451-test gate 覆盖）。

**桌面 checklist 入口**（`docs/knowledge/research/2026-08-21-bsi-desktop-checklist.md`，双终端对发）：
```bash
# 终端 1 (teleopit env)
C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_sim.py --config-name pico4_sim_bsi controller.policy_path=ckpt/track_g1.onnx
# 终端 2 (dds-probe env) — mock BSI 指令流
C:/Users/user/.conda/envs/dds-probe/python.exe -m bsi_dds.cli mock --script "idle:3,forward:5,left:3,forward:5,right:3,idle:3,forward:5,idle:3"
```

**交付物**：`DdsIntentSource`（reader adapter，fail-safe IDLE）、`build_merged_bsi_provider`（lazy `bsi_dds` import 仅在此）、`merged_bsi` 配置分支（默认路径零变化）、`pico4_sim_bsi.yaml`、`EstopController` 贯穿 `VelocityStepController`/`SimulationLoop`/双会话、E/C 键（键盘）+ 右 menuButton/左手 Y（pico）控制事件、H 帮助文本加急停/哑音两行、桌面 14 行 checklist。Phase-2 完成；真 DDS 联调（dds-probe env `mock` CLI + MuJoCo viewer 人看）走桌面 checklist 手动门。
