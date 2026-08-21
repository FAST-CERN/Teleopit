# Pico Sim VELOCITY Mode — Operator Visual Check (2026-08-20)

Launch (worktree root):
`C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_sim.py --config-name pico4_sim_velocity controller.policy_path=ckpt/track_g1.onnx`

Preconditions: Pico 4 bridge running (pico-bridge APK), operator wearing HMD,
controllers on, three viewers open, console in STANDING.

| # | Check | Expected | Result |
|---|-------|----------|--------|
| 1 | Launch | Console shows STANDING; G1 stands at pose B | PASS |
| 2 | V (from STANDING) | Mode -> VELOCITY log; robot stays standing, no visible jump | PASS |
| 3 | Left stick forward | Robot walks forward; speed follows stick | PASS |
| 4 | Left stick L/R; right stick X | Strafes; turns in place | PASS |
| 5 | Release sticks | Decelerates to standing still | PASS |
| 6 | X | Ramps back to pose-B STANDING; heading preserved (no snap to yaw 0) | PASS |
| 7 | Y then V | V rejected: "requires STANDING" (MOCAP direct switch forbidden) | PASS |
| 8 | X from MOCAP, then V | Returns to STANDING; V now works | PASS |
| 9 | Bridge disconnect mid-VELOCITY | Robot stands still (joystick zero); NO auto mode-exit | PASS |
| 10 | Reconnect + Y | MOCAP resumes without re-warmup stall | PASS |
| 11 | Skeleton viewer during VELOCITY | Operator skeleton keeps animating | PASS |
| 12 | T-style tilt probe (optional) | Tilt past threshold returns STANDING | PASS |
| 13 | Keyboard fallback walk | Not applicable in pico session (pico4 input = joystick provider, no keyboard twist by design). Verified by design review 2026-08-21; dedicated entry run_velocity_sim.py covers the keyboard path (unit+integration tested) | N/A (by design) |

Notes for the operator (updated after the 2026-08-20 HMD session):

- **HMD session findings (fixed in the operator-fix commit, same day):**
  1. **Joystick lateral/turn directions were inverted** — pushing a stick
     right moved/turned the robot LEFT. Root cause: the policy's convention
     (Phase A keyboard gate) is lin_y>0 = LEFT strafe, ang_z>0 = LEFT (CCW)
     turn, while Unity stick +X is a physical push right. Fixed by negating
     the lateral/turn axes in `PicoJoystickProvider.get_cmd` (forward axis
     was already correct).
  2. **Full-forward stick tripped the joint-velocity safety gate** (12.0
     rad/s, calibrated at 1.0 m/s walking; a 2.0 m/s full-stick command
     exceeds it within seconds and STOPs the session by design). Fixed by
     `command.joystick.max_stick_scale: {lin_vel_x: 0.5}` — stick +1 now
     commands 1.0 m/s (the validated envelope); raise only after per-joint
     velocity limits replace the scalar gate (Phase B).
  3. **Keyboard fallback keys collided with mode keys** (q = quit vs
     turn-left, a = pause vs strafe-left, x = exit-VELOCITY vs zero-twist;
     the tee delivers every key to BOTH consumers). Twist keys remapped to
     W/S forward/back, J/L strafe, N/M turn, K zero — no session-key
     collisions. Applies to both the pico-config keyboard fallback and
     `run_velocity_sim.py`.
- **Row 13 background — keyboard-walk fallback needed the shared-reader tee
  fix; it is fixed.** When `input.provider` is `bvh`/`udp_bvh` the twist
  command falls back to keyboard (W/S + J/L + N/M). Before Task 6 the
  keyboard twist provider and SimLoopSession each owned a separate
  `TerminalKeyboardReader`; the session's reader polled first each iteration
  and drained every buffered key, silently dropping the twist keys, so the
  fallback could never move the robot — a lost input race. Now ONE
  `TerminalKeyboardReader` is wrapped in a `KeyboardTee`
  (`teleopit/commands/keyboard_tee.py`) and shared: both the session's mode
  keys and the twist keys receive every key batch within a policy step.
  Regression tests: `tests/test_keyboard_tee.py` (5) and
  `tests/test_sim_loop.py::test_session_uses_shared_keyboard_reader_when_velocity_stack_attachs_one`.
- **Deadzone hard-gate tuning note.** The joystick applies a hard 0.15
  deadzone with NO rescaling after it: deflection inside the deadzone maps to
  exactly zero, and just past the edge the forward command jumps from 0 to
  ~0.15 m/s (stick 0.15 x 2.0 limit x 0.5 scale cap). If the operator finds
  the on/off jump at the deadzone edge uncomfortable, a rescaled deadzone
  (remap the post-deadzone stick range onto [0, max]) is a small, isolated
  change in `teleopit/commands/pico_joystick.py` (`PicoJoystickProvider`);
  request it and it can be added without touching the policy or the mode
  machine.
- **Environment note (cost an hour on 2026-08-20):** teleopit is
  pip-installed editable pointing at the MAIN checkout. Running the worktree
  entry script without `PYTHONPATH` silently mixes worktree config with
  master code (V key exists in config but not in code — no feedback line at
  all). Always launch from the worktree with
  `$env:PYTHONPATH = "<worktree root>"` until the branch is merged.
- **Exact launch commands** (dual entries, both verified headless at Task 6):
  - Pico HMD session:
    `C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_sim.py --config-name pico4_sim_velocity controller.policy_path=ckpt/track_g1.onnx`
  - Keyboard-only twist sim (no HMD):
    `C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_velocity_sim.py controller.policy_path=ckpt/track_g1.onnx`
