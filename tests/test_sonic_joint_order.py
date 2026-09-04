"""SONIC joint-order mapping (sonic-wbc t02 TDD-1).

Guards the IsaacLab<->MuJoCo permutation against the SONIC deploy source
(``gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/include/policy_parameters.hpp``
lines 99-104, verified 2026-09-04 against clone HEAD 087f9ac) and the local
``assets/robots/unitree_g1/g1_29dof.xml`` blocked order (L leg 0-5, R leg
6-11, waist 12-14, L arm 15-21, R arm 22-28).

Index-set facts cross-checked against policy_parameters.hpp lines 76-97
(upper17 / wrist6 / lower12 in both orders).
"""
from __future__ import annotations

import numpy as np
import pytest

from teleopit.policies.sonic.joint_order import (
    ISAACLAB_TO_MUJOCO,
    LOWER12_MUJOCO_ORDER_IN_ISAACLAB,
    MUJOCO_TO_ISAACLAB,
    UPPER17_ISAACLAB,
    UPPER17_ISAACLAB_IN_MUJOCO,
    WRIST6_ISAACLAB,
    WRIST6_ISAACLAB_IN_MUJOCO,
    from_isaaclab_order,
    to_isaaclab_order,
)


class TestMappingArrays:
    def test_arrays_are_permutations_of_0_to_28(self):
        assert sorted(ISAACLAB_TO_MUJOCO) == list(range(29))
        assert sorted(MUJOCO_TO_ISAACLAB) == list(range(29))

    def test_arrays_are_exact_inverse(self):
        # mujoco_to_isaaclab[il] = mj; isaaclab_to_mujoco[mj] = il
        for il in range(29):
            assert ISAACLAB_TO_MUJOCO[MUJOCO_TO_ISAACLAB[il]] == il
        for mj in range(29):
            assert MUJOCO_TO_ISAACLAB[ISAACLAB_TO_MUJOCO[mj]] == mj

    def test_arrays_match_sonic_deploy_source(self):
        # policy_parameters.hpp:100-104, verbatim (whitespace removed).
        assert list(ISAACLAB_TO_MUJOCO) == [
            0, 3, 6, 9, 13, 17, 1, 4, 7, 10, 14, 18, 2, 5, 8,
            11, 15, 19, 21, 23, 25, 27, 12, 16, 20, 22, 24, 26, 28,
        ]
        assert list(MUJOCO_TO_ISAACLAB) == [
            0, 6, 12, 1, 7, 13, 2, 8, 14, 3, 9, 15, 22, 4, 10,
            16, 23, 5, 11, 17, 24, 18, 25, 19, 26, 20, 27, 21, 28,
        ]


class TestPermutationRoundTrip:
    def test_round_trip_random_vector(self):
        rng = np.random.default_rng(20260904)
        q_mj = rng.normal(size=29)
        back = from_isaaclab_order(to_isaaclab_order(q_mj))
        np.testing.assert_array_equal(back, q_mj)

    def test_to_isaaclab_places_value_at_expected_slot(self):
        q_mj = np.arange(29, dtype=float)
        q_il = to_isaaclab_order(q_mj)
        for il in range(29):
            assert q_il[il] == q_mj[MUJOCO_TO_ISAACLAB[il]]

    def test_rejects_wrong_length(self):
        with pytest.raises(ValueError):
            to_isaaclab_order(np.zeros(28))
        with pytest.raises(ValueError):
            from_isaaclab_order(np.zeros(30))


class TestIndexSets:
    def test_waist_isaac_indices(self):
        # waist_yaw/roll/pitch: MuJoCo 12,13,14 -> IsaacLab 2,5,8
        assert [ISAACLAB_TO_MUJOCO[mj] for mj in (12, 13, 14)] == [2, 5, 8]

    def test_wrist_isaac_set_maps_to_mujoco_blocked_arms(self):
        # IsaacLab wrists 23..28 -> MuJoCo {19,20,21} left + {26,27,28} right
        assert sorted(MUJOCO_TO_ISAACLAB[il] for il in WRIST6_ISAACLAB) == [19, 20, 21, 26, 27, 28]

    def test_upper17_isaac_set(self):
        # policy_parameters.hpp:80 verbatim
        assert list(UPPER17_ISAACLAB) == [2, 5, 8, 11, 12, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28]
        # Its image in MuJoCo indices is exactly the blocked upper body 12..28
        assert sorted(UPPER17_ISAACLAB_IN_MUJOCO) == list(range(12, 29))

    def test_lower12_mujoco_order_in_isaac(self):
        # policy_parameters.hpp:92 verbatim: legs in MuJoCo blocked order,
        # values expressed as IsaacLab indices.
        assert list(LOWER12_MUJOCO_ORDER_IN_ISAACLAB) == [0, 3, 6, 9, 13, 17, 1, 4, 7, 10, 14, 18]

    def test_wrist6_orderings(self):
        assert list(WRIST6_ISAACLAB) == [23, 24, 25, 26, 27, 28]
        assert list(WRIST6_ISAACLAB_IN_MUJOCO) == [19, 26, 20, 27, 21, 28]


class TestSemanticSpotChecks:
    """Anchor rows from the t01 mapping table (research/01 §2).

    Direction adjudicated via the upper-body cross tables (policy_parameters.hpp
    lines 76-97): ``isaaclab_to_mujoco[mj] = il`` despite the variable name
    reading the other way.
    """

    def test_left_elbow(self):
        assert ISAACLAB_TO_MUJOCO[18] == 21  # left_elbow: mj 18 -> il 21

    def test_right_hip_pitch(self):
        assert ISAACLAB_TO_MUJOCO[6] == 1  # right_hip_pitch: mj 6 -> il 1

    def test_left_shoulder_pitch(self):
        assert ISAACLAB_TO_MUJOCO[15] == 11  # left_shoulder_pitch: mj 15 -> il 11
