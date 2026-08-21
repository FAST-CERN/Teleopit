"""Inspire hand ctrl DDS idl binding — ported from manus_haptic_rt
(src/manus_haptic_rt/hand/dds_types.py, 2026-08-22). Imported ONLY inside
the real publisher path; the teleopit test env has no cyclonedds.

Import style mirrors the source verbatim (cyclonedds.idl.types long path —
cyclonedds 0.10.x does not expose `types` at the package top level).
"""
from dataclasses import dataclass

import cyclonedds.idl as idl
import cyclonedds.idl.annotations as annotate
import cyclonedds.idl.types as types


@dataclass
@annotate.final
@annotate.autoid("sequential")
class InspireHandCtrl(idl.IdlStruct, typename="inspire.inspire_hand_ctrl"):
    pos_set: types.sequence[types.int16, 6]
    angle_set: types.sequence[types.int16, 6]
    force_set: types.sequence[types.int16, 6]
    speed_set: types.sequence[types.int16, 6]
    mode: types.int8
