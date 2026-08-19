"""Run the STANDING<->VELOCITY twist cmd_vel simulation (G1 sim2sim).

Keys: v = enter VELOCITY, b = back to STANDING, Esc = stop.
Twist: w/s fwd/back, a/d strafe, q/e turn, x = zero.

Examples:
  python scripts/run/run_velocity_sim.py                       # interactive
  python scripts/run/run_velocity_sim.py controller.policy_path=ckpt/track_g1.onnx
  python scripts/run/run_velocity_sim.py num_steps=50 realtime=false viewers=none  # headless smoke
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

import hydra
import numpy as np
from omegaconf import DictConfig

from teleopit.commands import KeyboardTwistProvider
from teleopit.robots.mujoco_robot import MuJoCoRobot
from teleopit.runtime.cli import validate_policy_path
from teleopit.runtime.common import cfg_get, parse_viewers
from teleopit.runtime.console import (
    KeyboardControl,
    PlainConsole,
    configure_runtime_logging,
)
from teleopit.runtime.factory import build_velocity_components
from teleopit.runtime.terminal_keyboard import TerminalKeyboardReader
from teleopit.sim.runtime_components import PolicyStepRunner, ViewerManager
from teleopit.sim.velocity_session import VelocityMode, VelocitySimSession
from teleopit.sim.viewer_subprocess import (
    mocap_viewer_proc,
    start_camera_viewer,
    start_robot_viewer,
)

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _KeyboardTee:
    """Deliver one physical key batch to every consumer within a step.

    The session (mode keys v/b/Esc) and the twist provider (WASD/QE/x) share
    one terminal reader and both call poll() per policy step; in VELOCITY mode
    the provider polls first and would otherwise drain and drop the mode keys
    before the session ever sees them. The tee caches one drained batch and
    hands the same batch to every poll() inside a single policy period, so
    both consumers act on disjoint key sets. Redelivery across periods is
    benign: request_mode collapses duplicate requests and the provider's
    latching is absolute (idempotent), never incremental.
    """

    def __init__(self, reader: TerminalKeyboardReader, refresh_s: float) -> None:
        self._reader = reader
        self._refresh_s = float(refresh_s)
        self._last_drain = 0.0
        self._batch: tuple[Any, ...] = ()

    def poll(self) -> tuple[Any, ...]:
        now = time.monotonic()
        if now - self._last_drain >= self._refresh_s:
            self._batch = self._reader.poll()
            self._last_drain = now
        return self._batch

    def close(self) -> None:
        self._reader.close()


class _ViewerMirroringRunner(PolicyStepRunner):
    """PolicyStepRunner that mirrors each applied step into the sim2sim viewer.

    Matches SimLoopSession, which writes the viewer right after every
    apply_control (teleopit/sim/session.py). Closing the viewer window
    requests STOP so the session ends cleanly, mirroring SimLoopSession's
    any_active() loop guard.
    """

    def __init__(self, *, viewer_manager: ViewerManager, on_viewer_closed: Callable[[], None], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._viewer_manager = viewer_manager
        self._on_viewer_closed = on_viewer_closed

    def apply_control(self, target_dof_pos: np.ndarray):
        torque, final_state = super().apply_control(target_dof_pos)
        self._viewer_manager.write_sim2sim(self.robot)
        if self._viewer_manager.has_viewers() and not self._viewer_manager.any_active():
            self._on_viewer_closed()
        return torque, final_state


def _resolve_policy_paths(cfg: DictConfig) -> None:
    """Rewrite relative policy paths against the project root (cwd-independent)."""
    sections = []
    controller_cfg = getattr(cfg, "controller", None)
    if controller_cfg is not None:
        sections.append(controller_cfg)
    controllers_cfg = getattr(cfg, "controllers", None)
    velocity_cfg = getattr(controllers_cfg, "velocity", None) if controllers_cfg is not None else None
    if velocity_cfg is not None:
        sections.append(velocity_cfg)
    for section in sections:
        raw = str(getattr(section, "policy_path", "") or "").strip()
        if raw and raw != "None":
            path = Path(raw).expanduser()
            if not path.is_absolute():
                section.policy_path = str((PROJECT_ROOT / path).resolve())


def _make_runner(
    robot: MuJoCoRobot,
    controller: Any,
    obs_builder: Any,
    sim_cfg: dict[str, object],
    decimation: int,
    viewer_manager: ViewerManager,
    on_viewer_closed: Callable[[], None],
) -> _ViewerMirroringRunner:
    return _ViewerMirroringRunner(
        viewer_manager=viewer_manager,
        on_viewer_closed=on_viewer_closed,
        robot=robot,
        controller=controller,
        obs_builder=obs_builder,
        policy_hz=float(sim_cfg["policy_hz"]),
        decimation=decimation,
        num_actions=robot.num_actions,
        kps=np.asarray(robot.kps, dtype=np.float32),
        kds=np.asarray(robot.kds, dtype=np.float32),
        torque_limits=np.asarray(robot.torque_limits, dtype=np.float32),
        default_dof_pos=np.asarray(robot.default_dof_pos, dtype=np.float32),
    )


def _velocity_operator_controls() -> tuple[KeyboardControl, ...]:
    return (
        KeyboardControl("V", "velocity"),
        KeyboardControl("B", "standing"),
        KeyboardControl("Esc", "stop"),
        KeyboardControl("W/S", "fwd/back"),
        KeyboardControl("A/D", "strafe"),
        KeyboardControl("Q/E", "turn"),
        KeyboardControl("X", "zero twist"),
    )


@hydra.main(
    version_base=None,
    config_path="../../teleopit/configs",
    config_name="velocity_sim",
)
def main(cfg: DictConfig) -> None:
    configure_runtime_logging(cfg, force=True)
    _resolve_policy_paths(cfg)
    validate_policy_path(cfg, "run_velocity_sim.py")
    console = PlainConsole(title="Teleopit velocity sim")

    components = build_velocity_components(cfg, PROJECT_ROOT, robot_cls=MuJoCoRobot)
    robot = components.robot

    sim_cfg = components.sim_cfg
    pd_hz = float(sim_cfg["pd_hz"])
    policy_hz = float(sim_cfg["policy_hz"])
    decimation = int(round(pd_hz / policy_hz))
    if abs(pd_hz / policy_hz - decimation) > 1e-6:
        raise ValueError(f"pd_hz/policy_hz must be an integer ratio, got {pd_hz / policy_hz}")

    viewer_manager = ViewerManager(
        robot=robot,
        viewers=parse_viewers(cfg),
        start_robot_viewer=start_robot_viewer,
        start_camera_viewer=start_camera_viewer,
        mocap_viewer_proc=mocap_viewer_proc,
    )
    viewer_manager.wait_until_ready(timeout_s=10.0)

    keyboard = TerminalKeyboardReader()
    if not keyboard.active:
        keyboard.close()
        keyboard = None
    tee = _KeyboardTee(keyboard, refresh_s=1.0 / policy_hz) if keyboard is not None else None
    command_cfg = components.command_cfg
    speeds = cfg_get(cfg_get(command_cfg, "keyboard", {}), "speeds", None)
    cmd_provider = KeyboardTwistProvider(speeds=speeds, keyboard=tee)

    def _on_viewer_closed() -> None:
        session.request_mode(VelocityMode.STOP)

    # pose_b single source of truth: the velocity obs builder was constructed
    # from controllers.velocity.default_dof_pos, so this can never drift from
    # the policy's neutral pose.
    session = VelocitySimSession(
        robot=robot,
        mimic_runner=_make_runner(
            robot, components.mimic_controller, components.mimic_obs_builder,
            sim_cfg, decimation, viewer_manager, _on_viewer_closed,
        ),
        velocity_runner=_make_runner(
            robot, components.velocity_controller, components.velocity_obs_builder,
            sim_cfg, decimation, viewer_manager, _on_viewer_closed,
        ),
        command_provider=cmd_provider,
        cfg={
            "policy_hz": policy_hz,
            "realtime": bool(cfg_get(cfg, "realtime", False)),
            "pose_b": list(components.velocity_obs_builder.default_dof_pos),
            "modes": dict(cfg_get(cfg, "modes", {}) or {}),
            "safety": dict(cfg_get(cfg, "safety", {}) or {}),
        },
        console=console,
        keyboard=tee,
    )

    console.start(
        status=(
            ("State", "STANDING"),
            ("Input", "keyboard twist"),
            ("Viewers", str(cfg_get(cfg, "viewers", "none"))),
        ),
        controls=_velocity_operator_controls(),
        events=("v enters VELOCITY; b returns to STANDING; Esc stops",),
        control_section="Controls",
        show_help_key=False,
    )
    logger.info(
        "sim ready | initial=STANDING | v=VELOCITY b=STANDING Esc=stop | WASD/QE twist, x=zero"
    )

    # Single-run contract: run() closes the command provider in its finally.
    num_steps = int(cfg_get(cfg, "num_steps", 0))
    try:
        summary = session.run(num_steps=num_steps)
    finally:
        viewer_manager.shutdown()
    console.event(f"summary: {summary}")
    logger.info("summary: %s", summary)


if __name__ == "__main__":
    main()
