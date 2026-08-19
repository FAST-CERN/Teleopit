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
