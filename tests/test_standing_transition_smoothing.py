"""MOCAP→STANDING reference-side transition smoothing (task #1, 2026-08-20).

Root cause of the observed X-key jitter (see SDD ledger / 2026-08-19 grilling
Q9): `_enter_standing` snapped the standing reference from the operator's last
mocap pose to the default standing pose in one step, and `_reset_policy_state`
zeroed prev_action. The kp ramp softened only the output torque. These tests
lock the ported fix: the reference ramps via StandingReferenceInterpolator
(the same mechanism the velocity channel uses), the ramp endpoint is adopted
as the standing reference (heading preserved, no snap-back), and prev_action
is kept across the mode switch.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from teleopit.sim2real.mp.runtime import _RobotControlWorker, RobotMode

FULL_QPOS_DIM = 36
ROOT_DIM = 7


def _worker_for_standing_entry(prev_mode: RobotMode) -> _RobotControlWorker:
    """Minimal worker exercising _enter_standing's transition arming.

    Mirrors the object.__new__ pattern of tests/test_high_level_policy.py.
    """
    worker = object.__new__(_RobotControlWorker)
    worker.high_level_policy_enabled = False
    worker.mode = prev_mode
    worker._policy_entry_pending = False
    worker._mocap_entry_requested = False
    worker._standing_ref_interp_duration_s = 1.0
    worker._standing_return_ramp_duration = 0.5
    worker._standing_return_kp_ramp_floor_ratio = 0.5
    worker.provider_kind = "pico4"

    yaw = np.pi / 2
    state = SimpleNamespace(
        quat=np.array([np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)]),
        qpos=np.full(29, 0.4, dtype=np.float64),  # deep crouch vs default pose
        base_pos=np.array([1.0, 2.0, 0.60]),
    )
    worker.robot = SimpleNamespace(
        get_state=lambda: state,
        enter_debug_mode=lambda: True,
        lock_all_joints=lambda: None,
    )
    worker._disarm_mocap_reference_if_needed = lambda: None
    worker._clear_reference_gate = lambda: None
    worker._stop_high_level_policy_session = lambda: None
    worker.default_angles = np.zeros(29, dtype=np.float32)
    worker._default_root_pos = np.array([0.0, 0.0, 0.793])
    worker.num_actions = 29
    worker._ref_proc = SimpleNamespace(last_reference_qpos=None, reset_smoothers=lambda: None, reset_alignment=lambda: None)
    worker._standing_qpos = np.zeros(FULL_QPOS_DIM, dtype=np.float64)
    worker._standing_qpos[3] = 1.0
    worker._reset_policy_state = lambda **_kw: None
    worker._safety = SimpleNamespace(start_kp_ramp=lambda **_kw: None)
    worker._mocap_session = SimpleNamespace(reset=lambda: None)
    worker._mocap_reentry_armed = False
    return worker


class TestEnterStandingArmsInterpolation:
    def test_mocap_to_standing_arms_reference_ramp(self):
        worker = _worker_for_standing_entry(RobotMode.MOCAP)
        worker._enter_standing()
        assert worker.mode == RobotMode.STANDING
        interp = worker._standing_ref_interp
        assert interp is not None, "MOCAP->STANDING must ramp the reference, not snap"

    def test_idle_to_standing_does_not_ramp(self):
        # Coming from a non-active mode there is no live pose to ramp from.
        worker = _worker_for_standing_entry(RobotMode.DAMPING)
        worker._enter_standing()
        assert worker._standing_ref_interp is None

    def test_ramp_endpoint_adopts_heading_and_current_xy(self):
        worker = _worker_for_standing_entry(RobotMode.MOCAP)
        worker._enter_standing()
        interp = worker._standing_ref_interp
        end = interp.sample(10.0)  # past duration
        end_yaw = 2.0 * np.arctan2(end[6], end[3])
        assert abs(end_yaw - np.pi / 2) < 1e-6, "endpoint must keep the robot's heading"
        np.testing.assert_allclose(end[0:2], [1.0, 2.0], atol=1e-9)


class TestStandingStepConsumesRamp:
    def _step_worker(self) -> tuple[_RobotControlWorker, list[np.ndarray]]:
        """Worker whose _standing_step records each commanded reference qpos."""
        worker = _worker_for_standing_entry(RobotMode.MOCAP)
        worker.policy_hz = 50.0
        worker._safety = SimpleNamespace(
            clip_to_joint_limits=lambda t: t,
            send_positions=lambda _t: None,
            start_kp_ramp=lambda **_kw: None,
        )
        worker.policy = SimpleNamespace(
            compute_action=lambda _obs: np.zeros(29, dtype=np.float32),
            get_target_dof_pos=lambda _a: np.zeros(29, dtype=np.float32),
        )
        worker._last_action = np.full(29, 0.3, dtype=np.float32)
        recorded_qpos: list[np.ndarray] = []

        ref_proc = SimpleNamespace(
            build_observation=lambda **_kw: np.zeros(167, dtype=np.float32),
            validate_observation=lambda obs: obs,
        )
        worker._ref_proc = ref_proc
        worker.obs_builder = SimpleNamespace()
        worker._reference_window_builder = None
        worker._publish_high_level_policy_observation = lambda _s: None
        worker._publish_record_step = lambda **_kw: recorded_qpos.append(_kw["reference_qpos"].copy())
        worker._write_retarget_viewer = lambda _q: None
        worker._standing_qpos[:] = 0.0
        worker._standing_qpos[3] = 1.0
        worker._standing_qpos[ROOT_DIM:] = 0.0
        return worker, recorded_qpos

    def test_reference_is_continuous_no_step_jump(self):
        worker, recorded = self._step_worker()
        worker._enter_standing()
        start_qpos = worker._last_retarget_qpos.copy()
        worker._standing_step()
        first = recorded[0]
        joint_jump = float(np.max(np.abs(first[ROOT_DIM:] - start_qpos[ROOT_DIM:])))
        # One policy step of a 1.0 s ramp moves at most ~1/50 of the gap —
        # versus the full gap (~0.4 rad/joint here) on the old snap.
        assert joint_jump < 0.4 / 40.0, f"reference snapped: {joint_jump:.3f} rad in one step"

    def test_ramp_finish_adopts_endpoint_no_snap_back(self):
        import time as _time

        worker, _ = self._step_worker()
        worker._enter_standing()
        # Force the ramp to be finished.
        worker._standing_ref_interp_t0 = _time.monotonic() - 10.0
        worker._standing_step()
        assert worker._standing_ref_interp is None
        end_yaw = 2.0 * np.arctan2(worker._standing_qpos[6], worker._standing_qpos[3])
        assert abs(end_yaw - np.pi / 2) < 1e-6, "post-ramp standing ref must keep heading"
        # A further step must not move the reference (adopted endpoint).
        before = worker._standing_qpos.copy()
        worker._standing_step()
        np.testing.assert_array_equal(worker._standing_qpos, before)

    def test_prev_action_survives_mode_switch(self):
        # Task #1 second half: _reset_policy_state previously zeroed
        # prev_action (a 167D obs channel); _enter_standing now calls it with
        # keep_last_action=True. Exercise the REAL _reset_policy_state with a
        # stubbed ref_proc/policy to prove the flag path preserves the action.
        worker = _worker_for_standing_entry(RobotMode.MOCAP)
        worker._reset_policy_state = _RobotControlWorker._reset_policy_state.__get__(worker)
        worker._ref_proc = SimpleNamespace(
            reset_smoothers=lambda: None, reset_alignment=lambda: None
        )
        worker._mocap_session = SimpleNamespace(reset=lambda: None)
        worker.policy = SimpleNamespace(reset=lambda: None)
        worker.obs_builder = SimpleNamespace(reset=lambda: None)
        seed = np.full(29, 0.3, dtype=np.float32)
        worker._last_action = seed.copy()

        worker._reset_policy_state(keep_last_action=True)

        np.testing.assert_array_equal(
            worker._last_action, seed, "keep_last_action=True must preserve prev_action"
        )

        # The default path still zeros (other callers unchanged).
        worker._reset_policy_state()
        np.testing.assert_array_equal(worker._last_action, np.zeros(29, dtype=np.float32))
