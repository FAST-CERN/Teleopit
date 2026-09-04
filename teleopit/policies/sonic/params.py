"""SONIC G1 29-DoF deploy constants (sonic-wbc t02).

Mirrors ``gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/include/
policy_parameters.hpp`` (clone HEAD 087f9ac). All vectors are in **MuJoCo
blocked order** (L leg 0-5, R leg 6-11, waist 12-14, L arm 15-21, R arm
22-28) — the hpp joint-name comments are the authority here; the policy's
action vector itself is IsaacLab-ordered and must be permuted via
:mod:`teleopit.policies.sonic.joint_order` before combining with these.

The default angles are identical to ``configs/robot/g1.yaml``; the action
scales differ from it at hip_pitch (SONIC's "new" 7520_22 motor table),
so this module carries its own numbers computed from the same motor
constants rather than reusing the local config.
"""
from __future__ import annotations

import numpy as np

# Motor armature / effort constants (policy_parameters.hpp:40-65).
_ARMATURE_5020 = 0.003609725
_ARMATURE_7520_14 = 0.01017752
_ARMATURE_7520_22 = 0.025101925
_ARMATURE_4010 = 0.00425
_NATURAL_FREQ = 10.0 * 2.0 * np.pi  # 10 Hz (hpp:46)
_EFFORT_5020 = 25.0
_EFFORT_7520_14 = 88.0
_EFFORT_7520_22 = 139.0
_EFFORT_4010 = 5.0

_STIFFNESS_5020 = _ARMATURE_5020 * _NATURAL_FREQ**2
_STIFFNESS_7520_14 = _ARMATURE_7520_14 * _NATURAL_FREQ**2
_STIFFNESS_7520_22 = _ARMATURE_7520_22 * _NATURAL_FREQ**2
_STIFFNESS_4010 = _ARMATURE_4010 * _NATURAL_FREQ**2


def _scale(effort: float, stiffness: float) -> float:
    """action_scale = 0.25 * effort_limit / stiffness (policy_parameters.hpp:27)."""
    return 0.25 * effort / stiffness


_S_HIP = _scale(_EFFORT_7520_22, _STIFFNESS_7520_22)   # hip pitch/roll, knee
_S_YAW = _scale(_EFFORT_7520_14, _STIFFNESS_7520_14)   # hip_yaw, waist_yaw
_S_5020 = _scale(_EFFORT_5020, _STIFFNESS_5020)        # ankle, waist r/p, shoulder/elbow/wrist_roll
_S_4010 = _scale(_EFFORT_4010, _STIFFNESS_4010)        # wrist pitch/yaw

# Default standing angles (policy_parameters.hpp:210-240), MuJoCo blocked order.
SONIC_DEFAULT_ANGLES_MJ: np.ndarray = np.array([
    -0.312, 0.0, 0.0, 0.669, -0.363, 0.0,
    -0.312, 0.0, 0.0, 0.669, -0.363, 0.0,
    0.0, 0.0, 0.0,
    0.2, 0.2, 0.0, 0.6, 0.0, 0.0, 0.0,
    0.2, -0.2, 0.0, 0.6, 0.0, 0.0, 0.0,
])

# Action scales (policy_parameters.hpp:109-139), MuJoCo blocked order.
SONIC_ACTION_SCALE_MJ: np.ndarray = np.array([
    _S_HIP, _S_HIP, _S_YAW, _S_HIP, _S_5020, _S_5020,
    _S_HIP, _S_HIP, _S_YAW, _S_HIP, _S_5020, _S_5020,
    _S_YAW, _S_5020, _S_5020,
    _S_5020, _S_5020, _S_5020, _S_5020, _S_5020, _S_4010, _S_4010,
    _S_5020, _S_5020, _S_5020, _S_5020, _S_5020, _S_4010, _S_4010,
])
