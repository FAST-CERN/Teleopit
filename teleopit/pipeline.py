from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
from omegaconf import DictConfig

from teleopit.bus.in_process import InProcessBus
from teleopit.controllers.observation import VelCmdObservationBuilder
from teleopit.controllers.rl_policy import RLPolicyController
from teleopit.inputs import BVHInputProvider, Pico4InputProvider
from teleopit.inputs.pico_video import PicoVideoRuntime, parse_pico_video_config
from teleopit.retargeting.core import RetargetingModule
from teleopit.robots.mujoco_robot import MuJoCoRobot
from teleopit.runtime.common import cfg_get
from teleopit.runtime.console import PlainConsole
from teleopit.runtime.factory import build_inference_components
from teleopit.sim.loop import SimulationLoop


def _select_cmd_provider_kind(input_provider_kind: str) -> str:
    """Joystick when pico drives, keyboard otherwise (locked decision 2)."""
    return "pico_joystick" if input_provider_kind == "pico4" else "keyboard"


class TeleopPipeline:
    def __init__(self, cfg: DictConfig | dict[str, Any], *, console: PlainConsole | None = None) -> None:
        self.cfg = cfg
        self._project_root = Path(__file__).resolve().parent.parent
        components = build_inference_components(
            cfg,
            self._project_root,
            robot_cls=MuJoCoRobot,
            controller_cls=RLPolicyController,
            obs_builder_cls=VelCmdObservationBuilder,
            bvh_input_cls=BVHInputProvider,
            pico4_input_cls=Pico4InputProvider,
            retargeter_cls=RetargetingModule,
        )

        self.robot = components.robot
        self.controller = components.controller
        self.obs_builder = components.obs_builder
        self.input_provider = components.input_provider
        self.retargeter = components.retargeter
        self.bus = InProcessBus()
        input_cfg = cfg_get(self.cfg, "input", {})
        self.video_runtime = PicoVideoRuntime(
            provider=self.input_provider,
            config=parse_pico_video_config(input_cfg),
            robot=self.robot,
        )
        self.loop = SimulationLoop(
            cast(Any, self.robot),
            cast(Any, self.controller),
            cast(Any, self.obs_builder),
            cast(Any, self.bus),
            components.sim_cfg,
            viewers=components.viewers,
            video_runtime=self.video_runtime,
            console=console,
        )

        controllers_cfg = cfg_get(self.cfg, "controllers", None)
        velocity_cfg = cfg_get(controllers_cfg, "velocity", None) if controllers_cfg is not None else None
        if velocity_cfg is not None:
            self._attach_velocity_stack(self.cfg)

    def _attach_velocity_stack(self, cfg: Any) -> None:
        """Build and attach the VELOCITY-mode stack when the config has one.

        The twist controller/builder pair comes from controllers.velocity
        (pose B, single-input ONNX); the command provider follows
        command.provider with a _select_cmd_provider_kind fallback.
        """
        from teleopit.commands import KeyboardTwistProvider, PicoJoystickProvider
        from teleopit.runtime.factory import build_velocity_policy_components

        velocity_controller, velocity_obs_builder = build_velocity_policy_components(
            cfg, self._project_root
        )
        input_provider_kind = str(cfg_get(cfg_get(cfg, "input", {}), "provider", "bvh")).lower()
        command_cfg = cfg_get(cfg, "command", {}) or {}
        selected = str(cfg_get(command_cfg, "provider", _select_cmd_provider_kind(input_provider_kind)))
        if selected == "pico_joystick":
            joystick_cfg = cfg_get(command_cfg, "joystick", {}) or {}
            cmd_provider = PicoJoystickProvider(
                self.input_provider,
                deadzone=float(cfg_get(joystick_cfg, "deadzone", 0.15)),
                max_age_s=float(cfg_get(joystick_cfg, "max_age_s", 0.5)),
            )
        else:
            from teleopit.runtime.terminal_keyboard import TerminalKeyboardReader

            speeds = cfg_get(cfg_get(command_cfg, "keyboard", {}), "speeds", None)
            # Own reader (WASD/QE keys are disjoint from the session's mode
            # keys): the pico entry keeps one session reader; the bvh/udp
            # fallback gets this second reader instead of a tee.
            keyboard = TerminalKeyboardReader()
            if not keyboard.active:
                keyboard.close()
                keyboard = None
            cmd_provider = KeyboardTwistProvider(speeds=speeds, keyboard=keyboard)
        safety_cfg = cfg_get(cfg, "safety", {}) or {}
        self.loop.attach_velocity_stack(
            velocity_controller=velocity_controller,
            velocity_obs_builder=velocity_obs_builder,
            cmd_provider=cmd_provider,
            transition_duration_s=float(
                cfg_get(cfg_get(cfg, "modes", {}), "transition_duration_s", 1.0)
            ),
            joint_vel_limit=float(cfg_get(safety_cfg, "joint_vel_limit", 12.0)),
            tilt_threshold_rad=float(cfg_get(safety_cfg, "tilt_threshold_rad", 1.0)),
            pose_b=np.asarray(velocity_obs_builder.default_dof_pos, dtype=np.float64),
        )

    def run(self, num_steps: int) -> dict[str, float | int | str]:
        if num_steps < 0:
            raise ValueError("num_steps must be non-negative (0 = infinite)")

        self.controller.reset()
        return dict(self.loop.run(cast(Any, self.input_provider), cast(Any, self.retargeter), num_steps=num_steps))
