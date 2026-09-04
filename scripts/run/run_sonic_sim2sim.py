"""Run the SONIC whole-body-control sim2sim loop (sonic-wbc t02).

Synthetic upper-body reference (anti-phase arm swing on the standing
template) through the real GEAR-SONIC low_latency checkpoint over the
local MuJoCo G1. The replay source line lands with mocap-map t06; this
entry exists to eyeball upper-body tracking and variant robustness now.

Examples:
  python scripts/run/run_sonic_sim2sim.py                          # 20 s, viewer, base XML
  python scripts/run/run_sonic_sim2sim.py --seconds 10 --variant combo
  python scripts/run/run_sonic_sim2sim.py --no-viewer --seconds 4   # headless smoke
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from omegaconf import OmegaConf  # noqa: E402

from teleopit.policies.sonic.runtime import SONIC_CKPT_DIR, SonicOnnxPolicy  # noqa: E402
from teleopit.robots.mujoco_robot import MuJoCoRobot  # noqa: E402
from teleopit.sim.sonic_gait import GaitClip, build_gait_stream, load_gait_clip  # noqa: E402
from teleopit.sim.sonic_session import SonicSimSession  # noqa: E402
from teleopit.sim.sonic_synthetic import make_synthetic_upperbody_stream  # noqa: E402
from teleopit.sim.sonic_variants import write_ballast_xml, write_locked_waist_xml  # noqa: E402

# The clip's first ~25 s is a standing segment (ticket 02 Progress #8);
# frame 1250 (t=25 s) starts the real walking stretch.
_GAIT_START_FRAME = 1250
_GAIT_NPZ = _REPO_ROOT / "assets" / "policies" / "sonic" / "sample_data" / "walk_forward_50hz.npz"


def _resolve_robot_cfg(variant: str) -> OmegaConf:
    cfg = OmegaConf.load(_REPO_ROOT / "teleopit" / "configs" / "robot" / "g1.yaml")
    xml = _REPO_ROOT / "assets" / "robots" / "unitree_g1" / "g1_29dof.xml"
    if not xml.exists():
        raise FileNotFoundError(f"G1 XML not found: {xml} (run the robots asset download)")
    if variant == "locked":
        xml = write_locked_waist_xml(xml)
    elif variant in ("ballast025p", "ballast05p"):
        mass = 0.25 if variant == "ballast025p" else 0.5
        xml = write_ballast_xml(xml, hand_mass_kg=mass, kind="point")
    elif variant in ("ballast05b",):
        xml = write_ballast_xml(xml, hand_mass_kg=0.5, kind="box")
    elif variant == "combo":
        xml = write_ballast_xml(write_locked_waist_xml(xml), hand_mass_kg=0.5, kind="box")
    elif variant != "base":
        raise ValueError(f"unknown variant {variant!r}")
    cfg.xml_path = str(xml)
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--variant", default="base",
                        choices=["base", "locked", "ballast025p", "ballast05p", "ballast05b", "combo"])
    parser.add_argument("--source", default="synthetic", choices=["synthetic", "gait"])
    parser.add_argument("--speed", type=float, default=None,
                        help="gait source: cmd speed m/s (default = clip segment native speed)")
    parser.add_argument("--speed-scale", type=float, default=1.0,
                        help="gait source: multiplier on the segment native speed")
    parser.add_argument("--yaw-rate", type=float, default=0.0, help="gait source: reference yaw rate rad/s")
    parser.add_argument("--period-s", type=float, default=2.0, help="synthetic arm-swing period")
    parser.add_argument("--elbow-rad", type=float, default=0.6, help="elbow swing amplitude")
    parser.add_argument("--no-viewer", action="store_true")
    parser.add_argument("--no-realtime", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for required in (SONIC_CKPT_DIR / "model_encoder.onnx", SONIC_CKPT_DIR / "model_decoder.onnx"):
        if not required.exists():
            logger.error("checkpoint missing: %s (see SonicOnnxPolicy error hint)", required)
            return 2

    policy_hz = 50.0
    robot = MuJoCoRobot(_resolve_robot_cfg(args.variant))
    policy = SonicOnnxPolicy()
    if args.source == "gait":
        if not _GAIT_NPZ.exists():
            logger.error("walk clip npz missing: %s (convert via tmp_convert_walk.py)", _GAIT_NPZ)
            return 2
        import numpy as np

        data = np.load(_GAIT_NPZ)
        dof = np.asarray(data["dof"])[_GAIT_START_FRAME:]
        trans = np.asarray(data["root_trans"])[_GAIT_START_FRAME:]
        n_seg = min(dof.shape[0], 600)  # 12 s of real walking
        seg_speed = float(np.linalg.norm(trans[n_seg] - trans[0]) / (n_seg * 0.02))
        speed = args.speed if args.speed is not None else args.speed_scale * seg_speed
        stream = build_gait_stream(
            GaitClip(joint_pos_mj=dof[:n_seg].copy(), native_speed=seg_speed),
            speed_mps=speed,
            duration_s=args.seconds + 2.0,
            yaw_rate=args.yaw_rate,
        )
        print(f"gait source: segment native {seg_speed:.3f} m/s, cmd {speed:.3f} m/s, yaw {args.yaw_rate}")
    else:
        stream = make_synthetic_upperbody_stream(
            duration_s=args.seconds + 2.0,
            policy_hz=policy_hz,
            elbow_amplitude_rad=args.elbow_rad,
            period_s=args.period_s,
        )
    session = SonicSimSession(robot=robot, policy=policy)
    session.attach_reference(stream)

    total_steps = int(round(args.seconds * policy_hz))
    viewer_ctx = None
    print(f"SONIC sim2sim: {args.seconds:.0f} s source={args.source}, variant={args.variant}, "
          f"policy=low_latency")

    if not args.no_viewer:
        import mujoco.viewer

        viewer_ctx = mujoco.viewer.launch_passive(robot.model, robot.data)

    trace: list[float] = []
    summaries = []
    wall_start = time.monotonic()
    try:
        with viewer_ctx if viewer_ctx is not None else _nullcontext():
            for step in range(total_steps):
                summary = session.run(1)
                summaries.append(summary)
                if step % int(policy_hz) == 0:
                    state = robot.get_state()
                    trace.append(float(state.base_pos[2]))
                    if summary["fell"]:
                        break
                if viewer_ctx is not None and step % 2 == 0:
                    viewer_ctx.sync()
                if not args.no_realtime:
                    target_t = (step + 1) / policy_hz
                    sleep_s = target_t - (time.monotonic() - wall_start)
                    if sleep_s > 0:
                        time.sleep(sleep_s)
    except KeyboardInterrupt:
        print("interrupted")
    finally:
        if viewer_ctx is not None:
            viewer_ctx.close()

    fell = any(s["fell"] for s in summaries)
    last = summaries[-1] if summaries else {}
    print(f"steps={len(summaries)} fell={fell} root_z_per_s={[round(z, 3) for z in trace]}")
    print(f"last-chunk summary: { {k: (round(v, 4) if isinstance(v, float) else v) for k, v in last.items()} }")
    return 0 if not fell else 1


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
