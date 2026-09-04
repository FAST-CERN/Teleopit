"""G1 XML variants for the SONIC sim2sim harness (sonic-wbc t02).

- locked waist: the three waist joints get ``range="0 0"`` (zero-travel ==
  welded; research/01 §5, decoupled_wbc precedent). Real robot waist is
  mode-locked, and SONIC's default waist angles are zero, so the policy's
  reference and observation stay self-consistent.
- RH56E2 ballast: explicit-mass geoms on both wrist_yaw_link bodies at the
  SONIC rubber-hand mount offset (0.0415, 0.003, 0); collision-free
  (contype/conaffinity 0), inertia from shape.

Variants are written next to the source XML (meshdir is relative to the
XML's directory; tmp_path breaks mesh resolution).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import find_g1_xml_path, requires_mujoco

from teleopit.sim.sonic_variants import (
    BALLAST_BODIES,
    BALLAST_MOUNT_POS,
    write_ballast_xml,
    write_locked_waist_xml,
)

_XML_PATH = find_g1_xml_path()
_skip_no_xml = pytest.mark.skipif(_XML_PATH is None, reason="Robot XML not found")


def _src() -> Path:
    return Path(_XML_PATH)


def _cleanup(*paths: Path) -> None:
    for p in paths:
        p.unlink(missing_ok=True)


@_skip_no_xml
class TestLockedWaistVariant:
    def test_ranges_zeroed_and_loadable(self):
        dst = write_locked_waist_xml(_src())
        try:
            text = dst.read_text(encoding="utf-8")
            for joint in ("waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint"):
                line = next(l for l in text.splitlines() if f'name="{joint}" axis' in l)
                assert 'range="0 0"' in line
            knee = next(l for l in text.splitlines() if 'name="left_knee_joint" axis' in l)
            assert 'range="0 0"' not in knee
            if _mujoco_available():
                import mujoco

                model = mujoco.MjModel.from_xml_path(str(dst))
                for joint in ("waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint"):
                    jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
                    assert model.jnt_range[jid][0] == 0.0
                    assert model.jnt_range[jid][1] == 0.0
        finally:
            _cleanup(dst)

    def test_dst_defaults_next_to_src(self):
        dst = write_locked_waist_xml(_src())
        try:
            assert dst.parent == _src().parent
            assert "locked_waist" in dst.name
        finally:
            _cleanup(dst)


def _mujoco_available() -> bool:
    try:
        import mujoco  # noqa: F401

        return True
    except ImportError:
        return False


@_skip_no_xml
class TestBallastVariant:
    def test_point_mass_added_to_both_wrists(self):
        import mujoco

        base = mujoco.MjModel.from_xml_path(_XML_PATH)
        dst = write_ballast_xml(_src(), hand_mass_kg=0.5, kind="point")
        try:
            model = mujoco.MjModel.from_xml_path(str(dst))
            for body in BALLAST_BODIES:
                added = model.body(body).mass - base.body(body).mass
                assert added == pytest.approx(0.5, rel=1e-6)
            bid = model.body("left_wrist_yaw_link").id
            geoms = [g for g in range(model.ngeom) if model.geom_bodyid[g] == bid]
            assert any(model.geom_contype[g] == 0 and model.geom_conaffinity[g] == 0 for g in geoms)
        finally:
            _cleanup(dst)

    def test_box_kind_distributes_inertia(self):
        import mujoco

        dst_p = write_ballast_xml(_src(), hand_mass_kg=0.5, kind="point")
        dst_b = write_ballast_xml(_src(), hand_mass_kg=0.5, kind="box")
        try:
            mp = mujoco.MjModel.from_xml_path(str(dst_p))
            mb = mujoco.MjModel.from_xml_path(str(dst_b))
            ip = mp.body("left_wrist_yaw_link").inertia
            ib = mb.body("left_wrist_yaw_link").inertia
            assert max(ib) > max(ip)  # box carries real rotational inertia
        finally:
            _cleanup(dst_p, dst_b)

    def test_both_hands_instrumented_with_mount_offset(self):
        dst = write_ballast_xml(_src(), hand_mass_kg=0.25, kind="point")
        try:
            text = dst.read_text(encoding="utf-8")
            pos = " ".join(f"{v:g}" for v in BALLAST_MOUNT_POS)
            for body in BALLAST_BODIES:
                geom_line = next(
                    l for l in text.splitlines() if f'name="{body}_rh56e2_marker"' in l
                )
                assert f'pos="{pos}"' in geom_line
                assert 'density="0"' in geom_line
        finally:
            _cleanup(dst)
