"""Shared PICO body-tracking 24-joint layout.

Owned here so the provider (parser of body frames), the tracker arm
synthesizer (producer of body-equivalent frames), and tests share one table
without import cycles.
"""

from __future__ import annotations

import numpy as np

BODY_JOINT_NAMES = [
    "Pelvis", "Left_Hip", "Right_Hip", "Spine1", "Left_Knee", "Right_Knee",
    "Spine2", "Left_Ankle", "Right_Ankle", "Spine3", "Left_Foot", "Right_Foot",
    "Neck", "Left_Collar", "Right_Collar", "Head", "Left_Shoulder", "Right_Shoulder",
    "Left_Elbow", "Right_Elbow", "Left_Wrist", "Right_Wrist", "Left_Hand", "Right_Hand",
]
BODY_JOINT_PARENTS = np.array(
    [
        -1,
        0, 0, 0, 1, 2,
        3, 4, 5, 6, 7, 8,
        9, 12, 12, 12, 13, 14,
        16, 17, 18, 19, 20, 21,
    ],
    dtype=np.int32,
)
