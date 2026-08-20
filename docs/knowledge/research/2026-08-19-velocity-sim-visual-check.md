# Velocity sim visual verification — Phase A manual gate (2026-08-19)

**Run command:**
```bash
python scripts/run/run_velocity_sim.py
```
The `viewers=sim2sim` flag opens the MuJoCo window automatically.

---

## Platform note

**Windows limitation:** The interactive keyboard control path is inactive on Windows. `TerminalKeyboardReader` uses termios (POSIX-only) and silently degrades to "no keyboard" on Windows terminals. On Windows, the MuJoCo viewer will launch and display the robot, but keyboard commands (w/s/a/d/q/e, v/b, x, Esc) will not respond.

**Interactive checklist requires:** A POSIX terminal (Linux, macOS, or WSL on Windows). If you only have Windows available, you can verify the visual rendering and initial standing pose, but cannot complete the full interactive checklist. Use WSL or a Linux/macOS environment for the full verification.

---

## Environment prerequisites

**Required:** Run with the conda `teleopit` interpreter and PYTHONPATH pointing to the repository checkout root:

```bash
# Activate the teleopit conda environment
conda activate teleopit

# Set PYTHONPATH to your repository checkout root
export PYTHONPATH=F:/Chufan_Rui/Teleopit

# Run the simulation
python scripts/run/run_velocity_sim.py
```

On Windows, the interpreter path is typically `C:/Users/user/.conda/envs/teleopit/python.exe` when running from a non-installed checkout.

---

## Keyboard controls

**Mode switching:**
- `v` — Transition from STANDING → VELOCITY mode
- `b` — Transition from VELOCITY → STANDING mode
- `Esc` — Emergency stop (freezes robot state with damping)

**Velocity commands (twist, body-frame):**
- `w` — Forward (+lin_x)
- `s` — Backward (−lin_x)
- `a` — Strafe left (−lin_y)
- `d` — Strafe right (+lin_y)
- `q` — Turn left (counterclockwise, +ang_z)
- `e` — Turn right (clockwise, −ang_z)

**Reset:**
- `x` — Zero all twist commands (stop walking, return to standing)

---

## Checklist

### STANDING (pose B)
- [ ] Robot stands stable at pose B (straighter knees than mimic pose A)
- [ ] No visible oscillation / trembling in knees or ankles
- [ ] Standing height > 0.6 m (measured 0.758 m — confirms pose B is upright)

### Transition STANDING → VELOCITY (press v)
- [ ] Hand-off at the switch instant: single smooth weight shift, NO visible jump or spasm in any joint at the moment v takes effect
- [ ] Gait starts within ~0.6 s (one phase period)
- [ ] Hand-off jump bound 0.25 rad (attractor floor 0.211 rad documented) is enforced by the pytest gate (`test_transition_jump_bounded`), which measures the last-standing→first-velocity target seam — do not read the session-cumulative console `max_target_jump_rad` for this

### VELOCITY walking (w/s/a/d/q/e, x = stop)
- [ ] w: walks FORWARD (if backward → joint order or sign bug, stop and file)
- [ ] a/d: strafes in the pressed direction
- [ ] q/e: turns in the pressed direction
- [ ] Turning while walking (w+q) does not trip
- [ ] Command tracking error: cmd_track_err_mps < 0.35 (measured 0.159 m/s)
- [ ] **Safety drill note:** At 1 m/s walking speed, knee peaks ~10.1 rad/s. The production `joint_vel_limit` is now 12.0 (user-ratified 2026-08-20; motor rated 20 rad/s, 40% margin), so a healthy walk should NOT trip the joint-velocity safety. If walking still stops with a joint-velocity log line, that is a real finding — record the logged peak value and file it.

### Transition VELOCITY → STANDING (press b)
- [ ] Gait terminates, robot settles to pose B without stumbling

### Safety drills
- [ ] **Tilt observation sanity:** While walking, manually push the robot in sim (apply external force via MuJoCo viewer ctrl-drag) beyond the tilt threshold → auto-returns to STANDING, does not keep walking while falling
- [ ] **Esc emergency stop:** Pressing Esc stops stepping immediately; robot state frozen consistent with damping semantics (no drift, no continued actuation)

### Metrics cross-check
- [ ] Console summary shows:
  - `max_target_jump_rad` — the 0.25 bound applies ONLY to the STANDING→VELOCITY hand-off moment (the automated gate measures exactly that seam in pytest: `tests/test_velocity_integration.py::test_transition_jump_bounded`). **Do NOT fail the run on this console value:** it accumulates over the WHOLE session, and during active gait a 50 Hz walking policy legitimately moves knee/ankle targets by 0.3-0.85 rad per step — so after any walking the session-cumulative value is EXPECTED to exceed 0.25 and that is not a failure. Use the hand-off checklist item above (watch the switch instant: single smooth weight shift, no visible jump/spasm) as the observational criterion; the numeric 0.25 check is done by the pytest gate.
  - `cmd_track_err_mps < 0.35` (measured 0.159 m/s in Task 8)
  - Standing height > 0.6 m (measured 0.758 m — pose B is upright)
- [ ] Record actual values here:
  - `max_target_jump_rad` = ___
  - `cmd_track_err_mps` = ___
  - `standing_height_m` = ___

---

## Outcome

**Result:** PASS / FAIL

**Notes (if FAIL):**
- Describe what failed and any console errors or warnings
- File findings in this document before proceeding to Phase B

**For FAIL results:** Document the specific checklist item(s) that failed, the observed behavior vs. expected behavior, and any console output or metrics that explain the deviation. This becomes the input to Phase B remediation.
