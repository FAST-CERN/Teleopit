"""G1 XML variants for the SONIC sim2sim harness (sonic-wbc t02).

Generated **next to the source XML** (meshdir is relative to the XML
location, so the variant must live in the same directory; the assets tree
is gitignored, so these are build artifacts, not checked-in models):

- **locked waist**: zero-travel ranges on the three waist joints — the
  real robot runs waist-locked (mode_machine ≈ 6 on 29-DoF units) and
  SONIC's waist defaults are zero, so reference, obs and plant stay
  self-consistent without clamping policy actions (research/01 §5).
- **RH56E2 ballast**: explicit-mass, collision-free geoms at the SONIC
  rubber-hand mount offset on both ``wrist_yaw_link`` bodies. ``point``
  (tiny sphere) isolates the mass effect; ``box`` (hand-sized envelope)
  adds distributed rotational inertia. Four comparison tiers per
  research/01 §7: 0 / 0.25 point / 0.5 point / 0.5 box.
"""
from __future__ import annotations

import re
from pathlib import Path

WAIST_JOINTS = ("waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint")
BALLAST_BODIES = ("left_wrist_yaw_link", "right_wrist_yaw_link")
BALLAST_MOUNT_POS = (0.0415, 0.003, 0.0)

_POINT_SIZE = 0.02  # small sphere: negligible rotational inertia
_BOX_HALF = (0.045, 0.035, 0.0225)  # half-extents of ~0.09 x 0.07 x 0.045 m


def write_locked_waist_xml(src: Path, dst: Path | None = None) -> Path:
    src = Path(src)
    dst = Path(dst) if dst is not None else src.with_name(f"{src.stem}_locked_waist.xml")
    text = src.read_text(encoding="utf-8")

    def lock(line: str) -> str:
        for joint in WAIST_JOINTS:
            if f'name="{joint}" axis' in line:
                return re.sub(r'range="[^"]*"', 'range="0 0"', line)
        return line

    dst.write_text("\n".join(lock(l) for l in text.splitlines()) + "\n", encoding="utf-8")
    return dst


def write_ballast_xml(src: Path, dst: Path | None = None, *, hand_mass_kg: float, kind: str = "point") -> Path:
    """Add RH56E2 hand mass to both wrists.

    The wrist bodies carry explicit ``<inertial>`` tags, so geom masses are
    ignored by MuJoCo — the ballast must be merged into the inertial itself:

    - mass: old + hand_mass_kg
    - pos: CoM-weighted blend toward the SONIC rubber-hand mount offset
      (exact parallel-axis CoM)
    - diaginertia: +0 for ``point`` (mass-at-CoM idealisation);
      + m/12*(dy^2+dz^2, dx^2+dz^2, dx^2+dy^2) for ``box`` (box inertia
      about its own COM, element-wise in the body's principal frame —
      axes-alignment approximation, documented)

    A collision-free red marker geom is still inserted at the mount offset
    so the hand envelope is visible in the viewer (no physical effect).
    """
    if kind not in ("point", "box"):
        raise ValueError(f"kind must be 'point' or 'box', got {kind!r}")
    if hand_mass_kg <= 0:
        raise ValueError("hand_mass_kg must be positive")
    src = Path(src)
    stem = f"{src.stem}_ballast_{str(hand_mass_kg).replace('.', 'p')}{kind}"
    dst = Path(dst) if dst is not None else src.with_name(f"{stem}.xml")

    box_full = (2 * _BOX_HALF[0], 2 * _BOX_HALF[1], 2 * _BOX_HALF[2])
    diag_add = (
        (0.0, 0.0, 0.0)
        if kind == "point"
        else tuple(
            hand_mass_kg / 12.0 * (box_full[(i + 1) % 3] ** 2 + box_full[(i + 2) % 3] ** 2)
            for i in range(3)
        )
    )

    lines = src.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    patched = 0
    current_wrist: str | None = None
    inserted_markers = 0
    for line in lines:
        opened = next((b for b in BALLAST_BODIES if f'<body name="{b}"' in line), None)
        if opened is not None:
            current_wrist = opened
            out.append(line)
            continue
        if current_wrist is not None and "<inertial" in line:
            out.append(_patched_inertial(line, current_wrist, hand_mass_kg, diag_add))
            patched += 1
            continue
        out.append(line)
        if current_wrist is not None and f'<geom class="visual" mesh="{current_wrist}"' in line:
            indent = line[: len(line) - len(line.lstrip())]
            pos = " ".join(f"{v:g}" for v in BALLAST_MOUNT_POS)
            out.append(
                f'{indent}<geom name="{current_wrist}_rh56e2_marker" type="{"sphere" if kind == "point" else "box"}" '
                f'size="{f"{_POINT_SIZE:g}" if kind == "point" else " ".join(f"{v:g}" for v in _BOX_HALF)}" '
                f'pos="{pos}" density="0" contype="0" conaffinity="0" rgba="0.9 0.2 0.2 0.4" />'
            )
            inserted_markers += 1
            current_wrist = None
    if patched != len(BALLAST_BODIES) or inserted_markers != len(BALLAST_BODIES):
        raise ValueError(
            f"expected to patch {len(BALLAST_BODIES)} wrist inertials, got {patched} (markers {inserted_markers})"
        )

    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    return dst


def _patched_inertial(line: str, body: str, hand_mass_kg: float, diag_add: tuple[float, float, float]) -> str:
    mass = float(re.search(r'mass="([-0-9.eE+]+)"', line).group(1))
    pos = [float(v) for v in re.search(r'pos="([^"]+)"', line).group(1).split()]
    diag = [float(v) for v in re.search(r'diaginertia="([^"]+)"', line).group(1).split()]
    new_mass = mass + hand_mass_kg
    # CoM-weighted blend toward the mount offset (exact for parallel axis).
    w = hand_mass_kg / new_mass
    new_pos = [(1.0 - w) * p + w * m for p, m in zip(pos, BALLAST_MOUNT_POS)]
    new_diag = [d + a for d, a in zip(diag, diag_add)]
    line = re.sub(r'\bpos="[^"]+"', 'pos="{}"'.format(" ".join(f"{v:.9g}" for v in new_pos)), line, count=1)
    line = re.sub(r'\bmass="[^"]+"', 'mass="{:.9g}"'.format(new_mass), line, count=1)
    line = re.sub(
        r'\bdiaginertia="[^"]+"',
        'diaginertia="{}"'.format(" ".join(f"{v:.9g}" for v in new_diag)),
        line,
        count=1,
    )
    return line
