"""SONIC (GEAR-SONIC) joint-order constants and permutations (sonic-wbc t02).

SONIC's policy obs/action and the ZMQ ``pose`` protocol use the IsaacLab
*interleaved* joint order; the local MuJoCo XML
(``assets/robots/unitree_g1/g1_29dof.xml``) and ``robot/g1.yaml`` use the
URDF *blocked* order (L leg 0-5, R leg 6-11, waist 12-14, L arm 15-21,
R arm 22-28).

Source of truth: ``gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/include/
policy_parameters.hpp`` lines 76-104 (clone HEAD 087f9ac, verified 2026-09-04).
Do NOT copy orderings from SONIC's sim-loop yaml (stale ``WeakMotorJointIndex``
comments there are known-wrong — see research/01 §2 陷阱记录).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
from numpy.typing import NDArray

# isaaclab_to_mujoco[mj] = il — the IsaacLab index of MuJoCo joint mj.
ISAACLAB_TO_MUJOCO: tuple[int, ...] = (
    0, 3, 6, 9, 13, 17, 1, 4, 7, 10, 14, 18, 2, 5, 8,
    11, 15, 19, 21, 23, 25, 27, 12, 16, 20, 22, 24, 26, 28,
)

# mujoco_to_isaaclab[il] = mj — the MuJoCo index of IsaacLab joint il.
MUJOCO_TO_ISAACLAB: tuple[int, ...] = (
    0, 6, 12, 1, 7, 13, 2, 8, 14, 3, 9, 15, 22, 4, 10,
    16, 23, 5, 11, 17, 24, 18, 25, 19, 26, 20, 27, 21, 28,
)

# Upper-body 17 = waist 3 + arms 14, IsaacLab order (policy_parameters.hpp:80).
UPPER17_ISAACLAB: tuple[int, ...] = (2, 5, 8, 11, 12, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28)
# The same joints' MuJoCo indices (policy_parameters.hpp:81).
UPPER17_ISAACLAB_IN_MUJOCO: tuple[int, ...] = (12, 13, 14, 15, 22, 16, 23, 17, 24, 18, 25, 19, 26, 20, 27, 21, 28)

# Wrist 6 DoF, IsaacLab order (policy_parameters.hpp:88-89).
WRIST6_ISAACLAB: tuple[int, ...] = (23, 24, 25, 26, 27, 28)
WRIST6_ISAACLAB_IN_MUJOCO: tuple[int, ...] = (19, 26, 20, 27, 21, 28)

# Lower-body 12 in MuJoCo blocked order, values as IsaacLab indices
# (policy_parameters.hpp:92) — the encoder's lower-body branch ordering.
LOWER12_MUJOCO_ORDER_IN_ISAACLAB: tuple[int, ...] = (0, 3, 6, 9, 13, 17, 1, 4, 7, 10, 14, 18)


def to_isaaclab_order(q_mujoco: Sequence[float]) -> NDArray[np.float64]:
    """Permute a MuJoCo-blocked 29-vector into IsaacLab order."""
    arr = np.asarray(q_mujoco, dtype=np.float64).reshape(-1)
    if arr.shape[0] != 29:
        raise ValueError(f"expected 29 joints, got {arr.shape[0]}")
    return arr[list(MUJOCO_TO_ISAACLAB)]


def from_isaaclab_order(q_isaaclab: Sequence[float]) -> NDArray[np.float64]:
    """Permute an IsaacLab-order 29-vector into MuJoCo blocked order."""
    arr = np.asarray(q_isaaclab, dtype=np.float64).reshape(-1)
    if arr.shape[0] != 29:
        raise ValueError(f"expected 29 joints, got {arr.shape[0]}")
    return arr[list(ISAACLAB_TO_MUJOCO)]
