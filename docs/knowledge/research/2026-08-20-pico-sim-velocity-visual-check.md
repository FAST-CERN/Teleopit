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
| 13 | Keyboard fallback walk (bvh/udp_bvh input only; optional) | V then W: robot walks forward while mode keys (X to return) keep working — requires the shared keyboard-reader tee, fixed in Task 6 | |

Notes for the operator (added at Task 6):

- **Row 13 background — keyboard-walk fallback needed the shared-reader tee
  fix; it is fixed.** When `input.provider` is `bvh`/`udp_bvh` the twist
  command falls back to keyboard WASD/QE. Before Task 6 the keyboard twist
  provider and SimLoopSession each owned a separate `TerminalKeyboardReader`;
  the session's reader polled first each iteration and drained every buffered
  key, silently dropping w/s/d/e (keys the session does not use), so the
  fallback could never move the robot — a lost input race. Now ONE
  `TerminalKeyboardReader` is wrapped in a `KeyboardTee`
  (`teleopit/commands/keyboard_tee.py`) and shared: both the session's mode
  keys and the twist keys receive every key batch within a policy step.
  Regression tests: `tests/test_keyboard_tee.py` (5) and
  `tests/test_sim_loop.py::test_session_uses_shared_keyboard_reader_when_velocity_stack_attachs_one`.
  - Key-overlap caveat that remains in the fallback: `q` turns left for the
    twist provider but ALSO quits the session, and `a` strafes left but also
    toggles mocap pause (in VELOCITY the session explicitly ignores `a`/`b`
    with an "ignored (VELOCITY)" message, but `q` quits from any mode). So in
    the keyboard fallback prefer `e` (turn right) / avoid holding `q` to
    turn; or use the dedicated keyboard entry `run_velocity_sim.py`, whose
    key map (v/b/Esc + WASD/QE/x) was designed with no collisions.
- **Deadzone hard-gate tuning note.** The joystick applies a hard 0.15
  deadzone with NO rescaling after it: deflection inside the deadzone maps to
  exactly zero, and just past the edge the forward command jumps from 0 to
  ~0.30 m/s (stick 0.15 x the 2.0 m/s forward limit). If the operator finds
  the on/off jump at the deadzone edge uncomfortable, a rescaled deadzone
  (remap the post-deadzone stick range onto [0, max]) is a small, isolated
  change in `teleopit/commands/pico_joystick.py` (`PicoJoystickProvider`);
  request it and it can be added without touching the policy or the mode
  machine.
- **Exact launch commands** (dual entries, both verified headless at Task 6):
  - Pico HMD session:
    `C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_sim.py --config-name pico4_sim_velocity controller.policy_path=ckpt/track_g1.onnx`
  - Keyboard-only twist sim (no HMD):
    `C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_velocity_sim.py controller.policy_path=ckpt/track_g1.onnx`
