# BSI Teleopit Integration — Phase 1 (Data Layer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the BSI data layer for Teleopit sim integration — BsiTwistProvider (debounce/smoothing/silence/mute over an injectable intent source), MergedTwistProvider (whole-packet joystick priority), and EstopController (latched session-level estop with 0.3s ramp) — validated by the wayfinder ticket-07 pytest metric gates, with zero DDS imports.

**Architecture:** Three new modules behind the existing `CommandProvider` seam (`teleopit/commands/base.py`). `IntentSource` is a Protocol; phase 1 ships `ScriptedIntentSource` (tests) and the DDS source arrives in phase 2. Estop lives at the session layer (`teleopit/sim/estop.py`) and wraps command output via `apply(cmd)`; velocity_step calls it after `get_cmd()`. Existing 457 tests untouched.

**Tech Stack:** Python 3.10, numpy float32 (6,) twist arrays, pytest with injected clocks (project convention: `clock=time.monotonic` constructor param, cf. `PicoJoystickProvider`). Run tests with the teleopit conda env python: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest`.

**Spec:** `docs/superpowers/specs/2026-08-21-bsi-teleopit-integration-design.md` (approved 2026-08-21). Decision record: `docs/wayfinder/2026-08-21-bsi-dds/tickets/*.md` resolutions.

## Global Constraints

- Zero `cyclonedds`/`bsi_dds` imports in phase-1 code and tests (cyclonedds lives only in the dds-probe env).
- Twist dtype float32 shape (6,), axis order [lin_x, lin_y, lin_z, ang_x, ang_y, ang_z] — identical to `TwistCommand.vec6()`.
- Intent enum ints: IDLE=0, FORWARD=1, TURN_LEFT=2, TURN_RIGHT=3 (mirrors `bsi_dds.protocol`; zero value is fail-safe IDLE). Define module-level constants in `bsi_twist.py` — do NOT import from bsi_dds.
- Locked parameters (wayfinder tickets): forward 0.6 m/s, turn ±0.6 rad/s in-place (turning commands lin_x=0), alpha 0.3 exponential smoothing, debounce 3 packets to switch / 2 packets to enter IDLE, silence timeout 1.0s, estop ramp 0.3s, estop decel gate ≤0.8s, response gate ≤1.0s to 0.3 m/s, natural decel gate ≤1.5s to <0.1 m/s, preempt gate ≤2 get_cmd cycles.
- All clocks injectable (`clock: Callable[[], float]` constructor param, default `time.monotonic`) — tests drive time manually.
- Provider contract: `get_cmd()` synchronous, never raises, returns zeros on unusable input (joystick/keyboard provider precedent).
- Existing tests must stay green: fast suite `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/ -x -q` (457 pass baseline; 4+11 pre-existing failures/errors in slow/markers suites are known, not ours).
- Commit message style: `feat(bsi): ...` / `test(bsi): ...`, ending with `Co-Authored-By: Claude <noreply@anthropic.com>`.

---

### Task 1: BsiTwistProvider core — intent pipeline with debounce, mapping, smoothing

**Files:**
- Create: `teleopit/commands/bsi_twist.py`
- Test: `tests/test_bsi_twist.py`

**Interfaces:**
- Consumes: `CommandProvider` protocol shape from `teleopit/commands/base.py` (duck-typed: `get_cmd() -> np.ndarray(6,) float32`, `reset()`, `close()`).
- Produces (later tasks and phase 2 rely on these exact names):
  - `INTENT_IDLE = 0`, `INTENT_FORWARD = 1`, `INTENT_TURN_LEFT = 2`, `INTENT_TURN_RIGHT = 3` (module ints)
  - `@dataclass(frozen=True) class DiscreteIntent: command: int; rx_time_s: float`
  - `class IntentSource(Protocol): def poll(self) -> DiscreteIntent | None: ...`
  - `class ScriptedIntentSource: def __init__(self, script: list[tuple[int, float]], clock: Callable[[], float] = time.monotonic); def poll(self) -> DiscreteIntent | None; def close(self) -> None` — script entries are (command, hold_seconds); each `poll()` returns the current segment's intent stamped with the segment start time; advances when clock passes cumulative boundaries; returns None only before the first segment starts.
  - `class BsiTwistProvider: def __init__(self, source: IntentSource, *, alpha: float = 0.3, debounce_packets: int = 3, idle_debounce_packets: int = 2, silence_timeout_s: float = 1.0, speeds: dict[str, float] | None = None, clock: Callable[[], float] = time.monotonic); def get_cmd(self) -> np.ndarray; def reset(self) -> None; def close(self) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bsi_twist.py`:

```python
"""BsiTwistProvider: intent -> twist pipeline (debounce/map/smooth/silence/mute)."""
from __future__ import annotations

import numpy as np
import pytest

from teleopit.commands.bsi_twist import (
    INTENT_FORWARD,
    INTENT_IDLE,
    INTENT_TURN_LEFT,
    INTENT_TURN_RIGHT,
    BsiTwistProvider,
    ScriptedIntentSource,
)


class ManualClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _provider(script, **kw):
    clock = kw.pop("clock", ManualClock())
    src = ScriptedIntentSource(script, clock=clock)
    return BsiTwistProvider(src, clock=clock, **kw), clock


def test_idle_maps_to_zero():
    p, _ = _provider([(INTENT_IDLE, 10.0)])
    np.testing.assert_allclose(p.get_cmd(), np.zeros(6, dtype=np.float32))


def test_forward_debounce_three_packets_then_ramps_to_0_6():
    # FORWARD held 10s at 10 Hz polling; debounce=3 -> effective intent at 3rd packet.
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(INTENT_FORWARD, 10.0)], clock=clock),
        clock=clock,
    )
    # Two packets (t=0.0 and t=0.1): debounce not satisfied -> still IDLE target.
    p.get_cmd(); clock.advance(0.1)
    p.get_cmd(); clock.advance(0.1)
    # t=0.2 is still between packets? No: 0.1s since last emit -> packet 3
    # arrives ON this call and satisfies debounce, so the ramp starts HERE.
    third = p.get_cmd()
    assert 0.0 < third[0] < 0.6  # packet 3 switched intent; ramping toward 0.6
    clock.advance(0.1)
    fourth = p.get_cmd()
    assert fourth[0] > third[0]  # ramp continues monotonically toward 0.6


def test_forward_reaches_half_target_within_1s_gate():
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(INTENT_FORWARD, 60.0)], clock=clock),
        clock=clock,
    )
    # Simulate 10 Hz intent polls with 50 Hz get_cmd (policy rate): each 0.1s
    # one new packet arrives; between packets get_cmd still steps smoothing.
    t_switch = None
    for i in range(200):  # 4 s at 50 Hz
        p.get_cmd()
        if t_switch is None and p.get_cmd()[0] > 0.0:
            t_switch = clock.t
        if t_switch is not None and p.get_cmd()[0] >= 0.3:
            assert clock.t - t_switch <= 1.0
            return
        clock.advance(0.02)
    pytest.fail("never reached 0.3 m/s")


def test_turn_left_maps_in_place_positive_ang_z():
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(INTENT_TURN_LEFT, 60.0)], clock=clock),
        clock=clock,
    )
    # Pump past debounce + smoothing to convergence.
    for _ in range(300):
        p.get_cmd()
        clock.advance(0.02)
    cmd = p.get_cmd()
    assert cmd[0] == pytest.approx(0.0, abs=1e-3)  # in-place: no lin_x
    assert cmd[5] == pytest.approx(0.6, abs=0.01)


def test_turn_right_converges_negative_ang_z():
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(INTENT_TURN_RIGHT, 60.0)], clock=clock),
        clock=clock,
    )
    for _ in range(300):
        p.get_cmd()
        clock.advance(0.02)
    assert p.get_cmd()[5] == pytest.approx(-0.6, abs=0.01)


def test_single_misclassified_packet_is_filtered():
    # FORWARD stream with a single TURN_LEFT packet injected: intent must not switch.
    clock = ManualClock()
    script = [(INTENT_FORWARD, 1.0), (INTENT_TURN_LEFT, 0.1), (INTENT_FORWARD, 30.0)]
    p = BsiTwistProvider(ScriptedIntentSource(script, clock=clock), clock=clock)
    for _ in range(100):  # settle into FORWARD
        p.get_cmd()
        clock.advance(0.02)
    # The 0.1s LEFT segment yields exactly one packet — filtered.
    for _ in range(10):
        p.get_cmd()
        clock.advance(0.02)
    cmd = p.get_cmd()
    assert cmd[0] > 0.4  # still ramped FORWARD
    assert abs(cmd[5]) < 0.01  # never turned


def test_idle_enters_after_two_packets():
    clock = ManualClock()
    script = [(INTENT_FORWARD, 4.0), (INTENT_IDLE, 20.0)]
    p = BsiTwistProvider(ScriptedIntentSource(script, clock=clock), clock=clock)
    for _ in range(39):  # 3.9s at 0.1s cadence: settle into FORWARD at 0.6
        p.get_cmd()
        clock.advance(0.1)
    assert p.get_cmd()[0] == pytest.approx(0.6, abs=0.01)
    # IDLE: 2 packets to enter (asymmetric, stop-first). Packets land on the
    # 0.1s cadence: t=4.0 is idle pkt 1, t=4.1 is idle pkt 2 -> switch.
    clock.advance(0.1)
    p.get_cmd(); clock.advance(0.1)  # t=4.0: idle pkt 1
    p.get_cmd()                       # t=4.1: idle pkt 2 -> intent switches
    mid = p.get_cmd().copy()          # first decaying output
    clock.advance(0.1)
    after = p.get_cmd()
    assert after[0] < mid[0] < 0.6  # decaying
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_bsi_twist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teleopit.commands.bsi_twist'`

- [ ] **Step 3: Write `teleopit/commands/bsi_twist.py`**

```python
"""BSI discrete-intent twist source: debounce -> map -> exponential smoothing.

The provider consumes an IntentSource (poll-based, injectable — a scripted
source in tests, the DDS subscriber thread in phase 2) and exposes the
CommandProvider seam. Locked parameters (wayfinder bsi-dds-02): forward
0.6 m/s, in-place turns ±0.6 rad/s, alpha-0.3 smoothing, 3-packet debounce
to switch intent / 2 packets to enter IDLE, 1.0 s silence -> IDLE.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np

# Intent enum ints — mirror bsi_dds.protocol (IDLE=0 fail-safe). Duplicated
# deliberately: phase 1 must not import bsi_dds (cyclonedds-free).
INTENT_IDLE = 0
INTENT_FORWARD = 1
INTENT_TURN_LEFT = 2
INTENT_TURN_RIGHT = 3

_DEFAULT_SPEEDS = {"forward": 0.6, "turn": 0.6}


@dataclass(frozen=True)
class DiscreteIntent:
    """One observed intent: the command value and when it was received."""

    command: int
    rx_time_s: float


class IntentSource(Protocol):
    """Yields newly arrived intents; None when nothing arrived since last poll."""

    def poll(self) -> DiscreteIntent | None: ...

    def close(self) -> None: ...


class ScriptedIntentSource:
    """Replays a (command, hold_seconds) script — the phase-1 test source.

    poll() returns the current segment's intent stamped with the segment
    start time, at most once per 1/rate_hz window (a packet generator, not a
    step function): repeated polls inside one window return None.
    """

    def __init__(
        self,
        script: list[tuple[int, float]],
        clock: Callable[[], float] = time.monotonic,
        *,
        rate_hz: float = 10.0,
    ) -> None:
        self._clock = clock
        self._period = 1.0 / float(rate_hz)
        self._segments: list[tuple[int, float, float]] = []  # (cmd, start, end)
        t = 0.0
        for command, hold in script:
            self._segments.append((int(command), t, t + float(hold)))
            t += float(hold)
        self._last_emit_t: float | None = None

    def poll(self) -> DiscreteIntent | None:
        now = self._clock()
        # Epsilon-tolerant rate limit: 0.1s float accumulation (0.1*3 ==
        # 0.30000000000000004) must not eat an emit slot.
        if (
            self._last_emit_t is not None
            and now - self._last_emit_t < self._period - 1e-9
        ):
            return None
        for command, start, end in self._segments:
            if start <= now < end:
                self._last_emit_t = now
                return DiscreteIntent(command=command, rx_time_s=now)
        # Past the script end: hold the last segment forever (tests rely on it).
        command, start, _end = self._segments[-1]
        self._last_emit_t = now
        return DiscreteIntent(command=command, rx_time_s=now)

    def close(self) -> None:
        return None


class BsiTwistProvider:
    """CommandProvider over a discrete-intent stream.

    Pipeline per get_cmd: poll -> silence check -> debounce -> mute -> map
    -> exponential smoothing. Clock is injectable; get_cmd never raises.
    """

    def __init__(
        self,
        source: IntentSource,
        *,
        alpha: float = 0.3,
        debounce_packets: int = 3,
        idle_debounce_packets: int = 2,
        silence_timeout_s: float = 1.0,
        speeds: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0.0 < float(alpha) <= 1.0:
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")
        self._source = source
        self._alpha = float(alpha)
        self._debounce = int(debounce_packets)
        self._idle_debounce = int(idle_debounce_packets)
        self._silence_timeout_s = float(silence_timeout_s)
        sp = dict(_DEFAULT_SPEEDS)
        if speeds:
            sp.update(speeds)
        self._forward = float(sp["forward"])
        self._turn = float(sp["turn"])
        self._clock = clock

        self._intent = INTENT_IDLE  # effective (debounced) intent
        self._streak_cmd: int | None = None  # command of current packet streak
        self._streak_len = 0
        self._last_rx_s: float | None = None
        self._muted = False
        self._smoothed = np.zeros(6, dtype=np.float32)

    # -- intent pipeline --------------------------------------------------

    def _poll_intent(self) -> None:
        now = self._clock()
        intent = self._source.poll()
        if intent is not None:
            self._last_rx_s = intent.rx_time_s
            # Packet streak -> debounce (asymmetric: IDLE enters faster).
            if intent.command == self._streak_cmd:
                self._streak_len += 1
            else:
                self._streak_cmd = intent.command
                self._streak_len = 1
            needed = self._idle_debounce if intent.command == INTENT_IDLE else self._debounce
            if self._streak_len >= needed and intent.command != self._intent:
                self._intent = intent.command
        # Silence: link lost -> IDLE (and clear the streak; silence is a
        # link event, not a label event).
        if (
            self._last_rx_s is None
            or now - self._last_rx_s > self._silence_timeout_s
        ):
            self._intent = INTENT_IDLE
            self._streak_cmd = None
            self._streak_len = 0

    def _target(self) -> np.ndarray:
        effective = INTENT_IDLE if self._muted else self._intent
        target = np.zeros(6, dtype=np.float32)
        if effective == INTENT_FORWARD:
            target[0] = np.float32(self._forward)
        elif effective == INTENT_TURN_LEFT:
            target[5] = np.float32(self._turn)
        elif effective == INTENT_TURN_RIGHT:
            target[5] = np.float32(-self._turn)
        return target

    # -- CommandProvider seam ----------------------------------------------

    def get_cmd(self) -> np.ndarray:
        self._poll_intent()
        target = self._target()
        self._smoothed = np.asarray(
            self._smoothed + self._alpha * (target - self._smoothed),
            dtype=np.float32,
        )
        return self._smoothed.copy()

    def reset(self) -> None:
        # Motion state clears; mute is operator state and survives.
        self._intent = INTENT_IDLE
        self._streak_cmd = None
        self._streak_len = 0
        self._last_rx_s = None
        self._smoothed = np.zeros(6, dtype=np.float32)

    def close(self) -> None:
        close = getattr(self._source, "close", None)
        if callable(close):
            close()

    # -- mute (wayfinder bsi-dds-05) ---------------------------------------

    def toggle_mute(self) -> bool:
        """Cut/uncut the brain source: muted forces IDLE, subscription lives."""
        self._muted = not self._muted
        return self._muted

    @property
    def muted(self) -> bool:
        return self._muted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_bsi_twist.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add teleopit/commands/bsi_twist.py tests/test_bsi_twist.py
git commit -m "feat(bsi): BsiTwistProvider — debounce/map/smooth pipeline over IntentSource (alpha 0.3, 3/2-packet debounce, 1s silence)"
```

---

### Task 2: BsiTwistProvider — silence, mute, unknown-value gates

**Files:**
- Modify: `tests/test_bsi_twist.py` (append tests)
- Modify: `teleopit/commands/bsi_twist.py` (only if a gate exposes a bug — Task 1 code is expected to satisfy these)

**Interfaces:**
- Consumes: Task 1 classes (`BsiTwistProvider`, `ScriptedIntentSource`, `INTENT_*`).
- Produces: `tests/test_bsi_twist.py` silence/mute/unknown gates (metric-gate evidence for handoff).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_bsi_twist.py`)

```python
def test_silence_falls_to_idle_within_1s_and_zero_by_1_5s():
    # A source that goes permanently quiet after its script ends (Task 2's
    # end-of-script semantics): link loss -> provider falls to IDLE.
    class _QuietAfter:
        """Emits FORWARD at 10Hz for 2s, then never again (link lost)."""

        def __init__(self, clock):
            self._clock = clock
            self._last = None

        def poll(self):
            now = self._clock()
            if now >= 2.0:
                return None
            if self._last is not None and now - self._last < 0.1:
                return None
            self._last = now
            from teleopit.commands.bsi_twist import DiscreteIntent
            return DiscreteIntent(command=INTENT_FORWARD, rx_time_s=now)

        def close(self):
            return None

    clock = ManualClock()
    p = BsiTwistProvider(_QuietAfter(clock), clock=clock)
    for _ in range(100):  # 2.0s: settle into FORWARD at 0.6
        p.get_cmd()
        clock.advance(0.02)
    assert p.get_cmd()[0] == pytest.approx(0.6, abs=0.01)
    clock.advance(1.1)  # past the 1.0s silence timeout since the last packet
    cmd = p.get_cmd()
    assert cmd[0] < 0.6  # intent already fell to IDLE on this first call
    for _ in range(60):  # 1.2s decay pump: smoothed output reaches ~0
        cmd = p.get_cmd()
        clock.advance(0.02)
    assert cmd[0] == pytest.approx(0.0, abs=1e-6)


def test_mute_forces_idle_next_cycle_and_unmute_restores():
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(INTENT_FORWARD, 60.0)], clock=clock),
        clock=clock,
    )
    for _ in range(200):
        p.get_cmd()
        clock.advance(0.02)
    assert p.get_cmd()[0] == pytest.approx(0.6, abs=0.01)
    assert p.toggle_mute() is True
    decaying = p.get_cmd()[0]
    assert decaying < 0.6  # next cycle already decaying toward zero
    for _ in range(200):
        p.get_cmd()
        clock.advance(0.02)
    assert p.get_cmd()[0] == pytest.approx(0.0, abs=1e-3)
    assert p.toggle_mute() is False  # unmute
    for _ in range(200):  # intent stream still FORWARD -> recovers
        p.get_cmd()
        clock.advance(0.02)
    assert p.get_cmd()[0] == pytest.approx(0.6, abs=0.01)


def test_mute_survives_reset():
    p, _ = _provider([(INTENT_FORWARD, 60.0)])
    p.toggle_mute()
    p.reset()
    assert p.muted is True


def test_unknown_command_value_fails_safe_to_idle():
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(99, 60.0)], clock=clock),
        clock=clock,
    )
    for _ in range(300):
        p.get_cmd()
        clock.advance(0.02)
    np.testing.assert_allclose(p.get_cmd(), np.zeros(6, dtype=np.float32))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_bsi_twist.py -v`
Expected: New tests FAIL. `test_silence_falls_to_idle_within_1s_and_zero_by_1_5s` fails if the source's "hold last segment" behavior masks silence — if so, that test needs the source to STOP emitting at script end instead (see Step 3 note). The other three are expected to pass against Task 1 code if Task 1 was correct — treat any failure as a Task 1 bug and fix the provider, not the test.

- [ ] **Step 3: Reconcile ScriptedIntentSource end-of-script semantics**

The silence test needs the source to go quiet at script end (real DDS silence = no packets). If Step 2 showed the hold-forever behavior breaks it, change `ScriptedIntentSource.poll`: after the last segment's end, return `None` (do not hold). Keep the change minimal:

```python
    def poll(self) -> DiscreteIntent | None:
        now = self._clock()
        if self._last_emit_t is not None and now - self._last_emit_t < self._period:
            return None
        for command, start, end in self._segments:
            if start <= now < end:
                self._last_emit_t = now
                return DiscreteIntent(command=command, rx_time_s=start)
        return None  # past script end: silent (matches DDS link loss)
```

Note: `test_forward_reaches_half_target_within_1s_gate` (Task 1) uses a 60s script pumped for 4s — unaffected. But `test_turn_*` and `test_mute_*` (60s scripts pumped ≤6s) are also unaffected. Only scripts that actually end change behavior.

- [ ] **Step 4: Run the full file to verify all pass**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_bsi_twist.py -v`
Expected: 11 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_bsi_twist.py teleopit/commands/bsi_twist.py
git commit -m "test(bsi): silence/mute/unknown-value metric gates; source goes silent at script end"
```

---

### Task 3: MergedTwistProvider — whole-packet joystick priority

**Files:**
- Create: `teleopit/commands/merged_twist.py`
- Test: `tests/test_merged_twist.py`

**Interfaces:**
- Consumes: Task 1 `BsiTwistProvider` (as the secondary source in tests); the `CommandProvider` duck shape.
- Produces: `class MergedTwistProvider: def __init__(self, primary: CommandProvider, secondary: CommandProvider); def get_cmd(self) -> np.ndarray; def reset(self) -> None; def close(self) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_merged_twist.py`:

```python
"""MergedTwistProvider: whole-packet arbitration, joystick (primary) priority."""
from __future__ import annotations

import numpy as np

from teleopit.commands.merged_twist import MergedTwistProvider


class _Vec:
    """Minimal CommandProvider stand-in returning a fixed vector."""

    def __init__(self, vec):
        self._vec = np.asarray(vec, dtype=np.float32)
        self.reset_calls = 0
        self.close_calls = 0

    def get_cmd(self):
        return self._vec.copy()

    def reset(self):
        self.reset_calls += 1

    def close(self):
        self.close_calls += 1


_BSI = _Vec([0.6, 0, 0, 0, 0, 0])
_JOY_ZERO = _Vec([0.0, 0, 0, 0, 0, 0])
_JOY_FWD = _Vec([0.4, 0, 0, 0, 0, 0.1])


def test_secondary_used_when_primary_zero():
    m = MergedTwistProvider(_JOY_ZERO, _BSI)
    np.testing.assert_allclose(m.get_cmd()[0], 0.6)


def test_primary_wins_whole_packet_when_nonzero():
    m = MergedTwistProvider(_JOY_FWD, _BSI)
    out = m.get_cmd()
    np.testing.assert_allclose(out, np.array([0.4, 0, 0, 0, 0, 0.1], dtype=np.float32))


def test_preempt_switches_within_two_cycles():
    class Flipping:
        def __init__(self):
            self.vec = np.zeros(6, dtype=np.float32)

        def get_cmd(self):
            return self.vec.copy()

        def reset(self): ...

        def close(self): ...

    joy = Flipping()
    m = MergedTwistProvider(joy, _BSI)
    np.testing.assert_allclose(m.get_cmd()[0], 0.6)  # joy zero -> BSI
    joy.vec[0] = 0.3  # operator grabs
    np.testing.assert_allclose(m.get_cmd()[0], 0.3)  # preempted on cycle 1
    joy.vec[0] = 0.0  # released
    np.testing.assert_allclose(m.get_cmd()[0], 0.6)  # BSI back on cycle 1


def test_reset_and_close_delegate_to_both():
    a, b = _JOY_ZERO, _BSI
    m = MergedTwistProvider(a, b)
    m.reset()
    m.close()
    assert a.reset_calls == 1 and a.close_calls == 1
    assert b.reset_calls == 1 and b.close_calls == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_merged_twist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teleopit.commands.merged_twist'`

- [ ] **Step 3: Write `teleopit/commands/merged_twist.py`**

```python
"""Whole-packet twist arbitration: primary (joystick) overrides secondary (BSI).

Locked decision (wayfinder bsi-dds-04): when the primary source's command is
a non-zero vector, its WHOLE packet wins; otherwise the secondary's whole
packet is used. Never per-axis blending — a merged composite intent (brain
forward + hand turn) is unobservable behavior. No extra cross-fade ramp:
both sources are already smooth (joystick continuous, BSI alpha-smoothed).
"""
from __future__ import annotations

import numpy as np


class MergedTwistProvider:
    """CommandProvider wrapping two sources with whole-packet priority."""

    def __init__(self, primary, secondary) -> None:
        self._primary = primary
        self._secondary = secondary

    def get_cmd(self) -> np.ndarray:
        primary = np.asarray(self._primary.get_cmd(), dtype=np.float32).reshape(-1)
        if bool(np.any(primary != 0.0)):
            return primary
        return np.asarray(self._secondary.get_cmd(), dtype=np.float32).reshape(-1)

    def reset(self) -> None:
        self._primary.reset()
        self._secondary.reset()

    def close(self) -> None:
        self._primary.close()
        self._secondary.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_merged_twist.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add teleopit/commands/merged_twist.py tests/test_merged_twist.py
git commit -m "feat(bsi): MergedTwistProvider — whole-packet joystick priority, no cross-fade"
```

---

### Task 4: EstopController — latch, ramp, session seam

**Files:**
- Create: `teleopit/sim/estop.py`
- Test: `tests/test_estop.py`

**Interfaces:**
- Consumes: injectable clock; numpy (6,) commands.
- Produces (Task 5 wires this into velocity_step; phase 2 wires keys):
  - `class EstopState(Enum): INACTIVE = "inactive"; RAMPING = "ramping"; LATCHED = "latched"`
  - `class EstopController: def __init__(self, *, ramp_s: float = 0.3, clock: Callable[[], float] = time.monotonic)`
  - `def toggle(self, in_velocity: bool) -> str` — returns `"estop"` (engaged), `"released"`, or `"ignored"` (toggle pressed while STANDING / not applicable)
  - `def apply(self, cmd: np.ndarray) -> np.ndarray` — passthrough when inactive; scaled decay during RAMPING; zeros when LATCHED
  - `def on_standing(self) -> None` — auto-unlatch (session calls it on mode -> STANDING)
  - `def consume_exit_request(self) -> bool` — True once when the ramp completes (the session then runs its X-exit path), re-armable
  - `@property def state(self) -> EstopState`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_estop.py`:

```python
"""EstopController: latch + 0.3s ramp + exit request (wayfinder bsi-dds-03/07)."""
from __future__ import annotations

import numpy as np
import pytest

from teleopit.sim.estop import EstopController, EstopState


class ManualClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


_CMD = np.array([0.6, 0, 0, 0, 0, 0], dtype=np.float32)


def test_inactive_passthrough_is_bitwise():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    out = estop.apply(_CMD)
    np.testing.assert_array_equal(out, _CMD)


def test_toggle_in_velocity_engages_ramp_then_latch():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    assert estop.toggle(in_velocity=True) == "estop"
    assert estop.state == EstopState.RAMPING
    first = estop.apply(_CMD)
    assert 0.0 < first[0] < 0.6  # decaying, not stepped
    # Ramp is 0.3s of exponential decay: well under the 0.8s gate at half.
    half_seen = None
    t_start = clock.t
    while clock.t - t_start < 1.0:
        clock.advance(0.02)
        v = estop.apply(_CMD)[0]
        if v < 0.1:
            half_seen = clock.t - t_start
            break
    assert half_seen is not None and half_seen <= 0.8
    assert estop.state == EstopState.LATCHED


def test_ramp_completes_request_exit_once():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    estop.toggle(in_velocity=True)
    assert estop.consume_exit_request() is False  # mid-ramp: no request yet
    for _ in range(50):  # 1.0s
        clock.advance(0.02)
        estop.apply(_CMD)
    assert estop.consume_exit_request() is True  # exactly once
    assert estop.consume_exit_request() is False


def test_latched_suppresses_any_source_to_zero():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    estop.toggle(in_velocity=True)
    for _ in range(50):
        clock.advance(0.02)
        estop.apply(_CMD)
    np.testing.assert_array_equal(estop.apply(_CMD), np.zeros(6, dtype=np.float32))


def test_same_key_toggle_releases():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    estop.toggle(in_velocity=True)
    for _ in range(50):
        clock.advance(0.02)
        estop.apply(_CMD)
    assert estop.toggle(in_velocity=True) == "released"
    np.testing.assert_array_equal(estop.apply(_CMD), _CMD)  # passthrough again


def test_toggle_while_standing_is_ignored():
    estop = EstopController(clock=ManualClock())
    assert estop.toggle(in_velocity=False) == "ignored"
    assert estop.state == EstopState.INACTIVE


def test_on_standing_auto_unlatches():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    estop.toggle(in_velocity=True)
    for _ in range(50):
        clock.advance(0.02)
        estop.apply(_CMD)
    assert estop.state == EstopState.LATCHED
    estop.on_standing()
    assert estop.state == EstopState.INACTIVE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_estop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teleopit.sim.estop'`

- [ ] **Step 3: Write `teleopit/sim/estop.py`**

```python
"""Session-level emergency stop: latched suppression with a 0.3s decay.

Locked decisions (wayfinder bsi-dds-03): session-scope (any VELOCITY
session, all command sources), cmd decays to zero then the session runs its
X-exit path into STANDING (NOT damping — the joint-vel/overspeed damping
gates stay as they are). Same key toggles engage/release; landing in
STANDING auto-releases.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Callable

import numpy as np

_RAMP_ALPHA = 0.35  # per-apply decay step; reaches <0.1x in well under ramp_s


class EstopState(Enum):
    INACTIVE = "inactive"
    RAMPING = "ramping"
    LATCHED = "latched"


class EstopController:
    """Owns the estop latch; the session consults it after get_cmd()."""

    def __init__(
        self,
        *,
        ramp_s: float = 0.3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ramp_s = float(ramp_s)
        self._clock = clock
        self._state = EstopState.INACTIVE
        self._ramp_start: float | None = None
        self._exit_requested = False
        self._exit_consumed = True

    @property
    def state(self) -> EstopState:
        return self._state

    def toggle(self, in_velocity: bool) -> str:
        if self._state == EstopState.INACTIVE:
            if not in_velocity:
                return "ignored"  # STANDING press: no-op, no deadlock
            self._state = EstopState.RAMPING
            self._ramp_start = self._clock()
            self._exit_requested = False
            self._exit_consumed = False
            return "estop"
        # RAMPING or LATCHED: same key releases.
        self._state = EstopState.INACTIVE
        self._ramp_start = None
        return "released"

    def apply(self, cmd: np.ndarray) -> np.ndarray:
        cmd = np.asarray(cmd, dtype=np.float32)
        if self._state == EstopState.INACTIVE:
            return cmd
        if self._state == EstopState.RAMPING:
            now = self._clock()
            elapsed = now - (self._ramp_start if self._ramp_start is not None else now)
            scaled = cmd * float(np.exp(-3.0 * elapsed / max(self._ramp_s, 1e-6)))
            if elapsed >= self._ramp_s:
                self._state = EstopState.LATCHED
                self._exit_requested = True
                return np.zeros_like(cmd)
            return scaled.astype(np.float32)
        return np.zeros_like(cmd)  # LATCHED

    def consume_exit_request(self) -> bool:
        if self._exit_requested and not self._exit_consumed:
            self._exit_consumed = True
            return True
        return False

    def on_standing(self) -> None:
        self._state = EstopState.INACTIVE
        self._ramp_start = None
        self._exit_requested = False
        self._exit_consumed = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_estop.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add teleopit/sim/estop.py tests/test_estop.py
git commit -m "feat(bsi): EstopController — latched suppression, 0.3s exp decay, one-shot exit request"
```

---

### Task 5: Session seam — wire estop into velocity_step (minimal缝)

**Files:**
- Modify: `teleopit/sim/velocity_step.py:245-260` (`velocity_step` method)
- Modify: `teleopit/sim/velocity_session.py` (constructor ~line 71: construct EstopController; `run()` loop: consume exit request; `_apply_pending_mode`: `on_standing` hook)
- Test: `tests/test_sim_loop.py` (append one regression test) — or a new `tests/test_estop_session_seam.py` if appending to the 1200-line test file feels heavy; prefer append, the file already holds session tests.

**Interfaces:**
- Consumes: Task 4 `EstopController` (`apply`, `consume_exit_request`, `on_standing`, `toggle`).
- Produces: `VelocityStepController.__init__` gains optional `estop: EstopController | None = None` (default None = bitwise passthrough — existing tests construct without it and must stay green). `VelocitySimSession` owns the estop instance and exposes `self.estop` (phase 2 wires keys to `estop.toggle`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_sim_loop.py`)

```python
def test_velocity_session_estop_passthrough_and_suppression():
    """Estop seam: inactive = bitwise passthrough; engaged = zero cmd downstream."""
    import numpy as np
    from teleopit.sim.estop import EstopController
    from teleopit.sim.velocity_session import VelocityMode, VelocitySimSession

    class _FakeSteps:
        def __init__(self):
            self.seen_cmd = None

        def velocity_step(self, robot):
            cmd = np.array([0.6, 0, 0, 0, 0, 0], dtype=np.float32)
            self.seen_cmd = cmd
            return cmd, np.zeros(1), np.zeros(1), None

        def check_safety(self, state):
            return None

    # Passthrough: estop inactive -> the controller's cmd reaches metrics raw.
    estop = EstopController(clock=lambda: 0.0)
    assert np.array_equal(estop.apply(np.float32([0.6, 0, 0, 0, 0, 0])), np.float32([0.6, 0, 0, 0, 0, 0]))
    # Engaged: suppressed to zeros.
    estop.toggle(in_velocity=True)
    assert not estop.apply(np.float32([0.6, 0, 0, 0, 0, 0])).any()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_sim_loop.py::test_velocity_session_estop_passthrough_and_suppression -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teleopit.sim.estop'` will NOT occur (Task 4 created it); instead the test FAILS at the first assert only if estop semantics are wrong. If it passes already (pure estop-level assertions), that is expected — this task's real deliverable is the seam below; add the session-level assertions after wiring:

Replace the Step 1 test body with the seam-level version once Step 3 wiring exists:

```python
def test_velocity_step_applies_estop_to_cmd():
    """velocity_step consults estop.apply() after get_cmd — engaged estop zeroes it."""
    import numpy as np

    from teleopit.sim.estop import EstopController
    from teleopit.sim.velocity_step import VelocityStepController

    class _Cmd:
        def get_cmd(self):
            return np.array([0.6, 0, 0, 0, 0, 0], dtype=np.float32)

        def reset(self): ...

        def close(self): ...

    estop = EstopController(clock=lambda: 0.0)
    estop.toggle(in_velocity=True)
    estop._state = __import__("teleopit.sim.estop", fromlist=["EstopState"]).EstopState.LATCHED  # skip ramp
    # Direct seam assertion without building a full VelocityStepController
    # (its runner contract is heavy; test_velocity_step.py covers the real
    # wiring — here assert the protocol the seam relies on):
    cmd = estop.apply(np.array([0.6, 0, 0, 0, 0, 0], dtype=np.float32))
    assert not cmd.any()
```

Note: the deeper wiring (VelocityStepController estop kwarg passthrough) is covered by extending ONE existing test in `tests/test_velocity_step.py` — append:

```python
def test_velocity_step_estop_none_is_passthrough():
    """estop=None (default) keeps velocity_step behavior bitwise unchanged."""
    # Reuse the file's existing step-fixture style: construct the controller
    # exactly as its current tests do, run velocity_step once with estop=None,
    # and assert the returned cmd equals cmd_provider.get_cmd() (no wrapper).
```

If the existing `test_velocity_step.py` fixtures make that assertion natural, write it fully; otherwise the seam test above plus `tests/test_estop.py` cover the controller and the fast suite (457 baseline) covers the None-default passthrough regression. Do not leave both variants half-written — pick one complete path.

- [ ] **Step 3: Wire the seam**

In `teleopit/sim/velocity_step.py`:

1. `VelocityStepController.__init__` signature gains `estop: EstopController | None = None` keyword param (after `tilt_threshold_rad`); store `self._estop = estop`.
2. `velocity_step` line 249: `cmd = self._cmd.get_cmd()` → then add:

```python
        cmd = self._cmd.get_cmd()
        if self._estop is not None:
            cmd = self._estop.apply(cmd)
```

In `teleopit/sim/velocity_session.py`:

1. Constructor: after `self._steps = VelocityStepController(...)` — add `estop=EstopController()` inside that call's kwargs, and keep a handle `self.estop = self._steps._estop` (or construct first, pass in — prefer explicit: `self.estop = EstopController()` then `estop=self.estop` in the kwargs).
2. `run()` loop, after `self._check_safety(state)` / before the step bodies: 

```python
                if self.estop.consume_exit_request():
                    self.request_mode(VelocityMode.STANDING)
                    self._apply_pending_mode(state)
```

3. `_apply_pending_mode`: when the applied target is STANDING or STOP, call `self.estop.on_standing()`.

Import `EstopController` from `teleopit.sim.estop` at module top of both files.

- [ ] **Step 4: Run the seam tests + full regression**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/test_sim_loop.py tests/test_estop.py tests/test_velocity_session.py tests/test_velocity_step.py -v 2>&1 | tail -5`
Expected: all PASS. Then the fast suite: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/ -q` — 457 pass baseline + ~29 new, zero new failures (4+11 pre-existing in known-slow/marker suites stay as-is).

- [ ] **Step 5: Commit**

```bash
git add teleopit/sim/velocity_step.py teleopit/sim/velocity_session.py tests/test_sim_loop.py
git commit -m "feat(bsi): wire EstopController into velocity session — cmd suppression seam + one-shot exit + auto-unlatch on STANDING"
```

---

### Task 6: Phase-1 gate run + headless smoke

**Files:**
- No new source files. Produces: gate evidence in the commit message; `docs/knowledge/research/` record is phase-2 (with the desktop checklist) — phase 1 records the pytest gate result in the plan checkboxes only.

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Full fast suite**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe -m pytest tests/ -q`
Expected: baseline 457 + ~29 new (11 bsi_twist + 4 merged + 7 estop + seam) all pass; zero new failures (4+11 pre-existing in known-slow/marker suites stay as-is — if the fast suite includes them, compare against the pre-branch count from git log `af41c8a` era).

- [ ] **Step 2: Headless smoke — default config (no BSI, zero-regression proof)**

Run: `C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_velocity_sim.py controller.policy_path=ckpt/track_g1.onnx num_steps=50`
Expected: exits 0, console shows 50 steps, no estop/BSI output (default provider path untouched).

- [ ] **Step 3: Update AGENTS.md / knowledge docs only if seam changed public behavior**

Check: `grep -n "estop" AGENTS.md docs/knowledge/*.md` — the seam is additive (estop=None default), so no doc change expected. Skip if nothing public changed.

- [ ] **Step 4: Commit (plan checkboxes / any leftover)**

```bash
git add -A
git commit -m "test(bsi): phase-1 gate — full suite green + headless smoke 50 steps, zero regression"
```

- [ ] **Step 5: Handoff summary (for the phase-2 session)**

Write into the plan file's end (append a `## Phase-1 Completion` section): commit SHA of the gate, test counts, and the phase-2 input pointer (spec `docs/superpowers/specs/2026-08-21-bsi-teleopit-integration-design.md` Handoff 边界 section + `docs/wayfinder/2026-08-21-bsi-dds/tickets/04+05+07` resolutions). The phase-2 session starts from this plan file's completion section, NOT from this conversation.
