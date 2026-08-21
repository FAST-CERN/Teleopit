"""Inspire hand ctrl DDS idl binding — ported from manus_haptic_rt
(src/manus_haptic_rt/hand/dds_types.py, 2026-08-22). Imported ONLY inside
the real publisher path; the teleopit test env has no cyclonedds.
"""
from dataclasses import dataclass

from cyclonedds import idl, types


@dataclass
@idl.final
@idl.autoid("sequential")
class InspireHandCtrl(idl.IdlStruct, typename="inspire.inspire_hand_ctrl"):
    pos_set: types.sequence[types.int16, 6]
    angle_set: types.sequence[types.int16, 6]
    force_set: types.sequence[types.int16, 6]
    speed_set: types.sequence[types.int16, 6]
    mode: types.int8
