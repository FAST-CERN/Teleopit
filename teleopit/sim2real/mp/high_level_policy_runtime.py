"""Independent high-level-policy sim2real process assembly.

This runtime deliberately does not start PicoBridge, GMR, or a reference
worker. It owns one RealSense stream and sends host-policy body references
through Teleopit's existing motion tracker.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
from multiprocessing.synchronize import Event as MpEvent
import time
from typing import Any, Callable

import numpy as np

from teleopit.high_level_policy.config import (
    parse_high_level_policy_camera_config,
    parse_high_level_policy_config,
    parse_high_level_policy_safety_config,
)
from teleopit.high_level_policy.hand_calibration import HandCalibration
from teleopit.high_level_policy.scheduler import closure_to_o6_pose
from teleopit.runtime.common import cfg_get
from teleopit.runtime.console import OPERATOR_LOGGER_NAME, PlainConsole
from teleopit.sim2real.hands.linkerhand_o6 import (
    LinkerHandO6Device,
    parse_linkerhand_o6_config,
)
from teleopit.sim2real.mp.high_level_policy_worker import HighLevelPolicyWorker
from teleopit.sim2real.mp.ipc import (
    COMMAND_TOPIC,
    HIGH_LEVEL_POLICY_TARGET_TOPIC,
    MODE_TOPIC,
    VIDEO_TOPIC,
    LatestSubscriber,
    Sim2RealIpcEndpoints,
    ZmqPublisher,
    default_endpoints,
)
from teleopit.sim2real.mp.messages import (
    CommandPacket,
    HighLevelPolicyTargetPacket,
    ModeStatePacket,
)
from teleopit.sim2real.mp.runtime import (
    HIGH_LEVEL_POLICY_FAULT_COMMAND,
    _mp_cfg,
    _plain_cfg,
    _run_robot_control_worker,
    _worker_loop,
)
from teleopit.sim2real.mp.shm import SharedFrameRingWriter
from teleopit.sim2real.neck.config import parse_neck_config
from teleopit.sim2real.neck.openneck import build_neck_device


logger = logging.getLogger(__name__)
operator_logger = logging.getLogger(OPERATOR_LOGGER_NAME)


class HighLevelPolicySim2RealRuntime:
    def __init__(self, cfg: Any, *, console: PlainConsole | None = None) -> None:
        self.cfg = _plain_cfg(cfg)
        _validate_high_level_policy_runtime_config(self.cfg)
        runtime_cfg = _mp_cfg(self.cfg)
        self._ctx = mp.get_context(str(cfg_get(runtime_cfg, "start_method", "spawn")))
        self._stop_event = self._ctx.Event()
        self._processes: list[mp.Process] = []
        self._shutdown_timeout_s = float(cfg_get(runtime_cfg, "shutdown_timeout_s", 3.0))
        self._endpoints = default_endpoints(
            host=str(cfg_get(runtime_cfg, "host", "127.0.0.1")),
            base_port=int(cfg_get(runtime_cfg, "base_port", 39700)),
        )
        self._command_pub: ZmqPublisher | None = None
        self._console = console or PlainConsole(title="Teleopit high-level policy", enabled=False)

    def run(self) -> None:
        operator_logger.info("high-level policy runtime starting")
        try:
            self._start_processes()
            self._command_pub = ZmqPublisher(self._endpoints.command_pub)
            reported_dead: set[str] = set()
            while not self._stop_event.is_set():
                time.sleep(0.2)
                critical_dead = [
                    process.name
                    for process in self._processes
                    if process.name == "robot_control"
                    and not process.is_alive()
                    and process.exitcode not in (None, 0)
                ]
                if critical_dead:
                    operator_logger.error("critical worker exited: %s", ", ".join(critical_dead))
                    self._stop_event.set()
                    break
                required_input_dead = [
                    process.name
                    for process in self._processes
                    if process.name in {"camera", "high_level_policy"}
                    and not process.is_alive()
                    and process.exitcode is not None
                ]
                if required_input_dead and self._command_pub is not None:
                    detail = (
                        "required high-level-policy input worker exited: "
                        + ", ".join(required_input_dead)
                    )
                    self._command_pub.publish(
                        COMMAND_TOPIC,
                        CommandPacket(
                            command=HIGH_LEVEL_POLICY_FAULT_COMMAND,
                            timestamp_s=time.monotonic(),
                            payload={"detail": detail},
                        ),
                    )
                noncritical_dead = [
                    process.name
                    for process in self._processes
                    if process.name != "robot_control"
                    and not process.is_alive()
                    and process.exitcode is not None
                    and process.name not in reported_dead
                ]
                if noncritical_dead:
                    operator_logger.warning(
                        "non-critical worker exited: %s; G1 remains under local control",
                        ", ".join(noncritical_dead),
                    )
                    reported_dead.update(noncritical_dead)
        except KeyboardInterrupt:
            operator_logger.info("keyboard interrupt -> shutting down")
            self._stop_event.set()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._command_pub is not None:
            self._command_pub.publish(
                COMMAND_TOPIC,
                CommandPacket(command="shutdown", timestamp_s=time.monotonic()),
            )
        for process in self._processes:
            process.join(timeout=self._shutdown_timeout_s)
        for process in self._processes:
            if process.is_alive():
                operator_logger.warning("terminating worker %s", process.name)
                process.terminate()
                process.join(timeout=1.0)
        self._processes.clear()
        if self._command_pub is not None:
            self._command_pub.close()
            self._command_pub = None

    def _start_processes(self) -> None:
        if self._processes:
            return
        specs: list[tuple[str, Callable[..., None]]] = [
            ("camera", _run_high_level_policy_camera_worker),
            ("high_level_policy", _run_high_level_policy_client_worker),
            ("robot_control", _run_robot_control_worker),
        ]
        hands_cfg = cfg_get(self.cfg, "hands", {}) or {}
        if bool(cfg_get(hands_cfg, "enabled", False)):
            specs.append(("policy_hand", _run_high_level_policy_hand_worker))
        neck_cfg = parse_neck_config(self.cfg)
        if neck_cfg.enabled:
            specs.append(("policy_neck", _run_high_level_policy_neck_worker))
        for name, target in specs:
            process = self._ctx.Process(
                name=name,
                target=target,
                args=(self.cfg, self._endpoints, self._stop_event),
            )
            process.start()
            self._processes.append(process)


def _validate_high_level_policy_runtime_config(cfg: dict[str, Any]) -> None:
    input_cfg = cfg_get(cfg, "input", {}) or {}
    if str(cfg_get(input_cfg, "provider", "")).strip().lower() != "high_level_policy":
        raise ValueError(
            "HighLevelPolicySim2RealRuntime requires input.provider=high_level_policy"
        )
    policy_cfg = cfg_get(cfg, "high_level_policy", {}) or {}
    if not bool(cfg_get(policy_cfg, "enabled", False)):
        raise ValueError("HighLevelPolicySim2RealRuntime requires high_level_policy.enabled=true")
    parse_high_level_policy_config(cfg)
    parse_high_level_policy_camera_config(cfg)
    parse_high_level_policy_safety_config(cfg)
    reference_steps = tuple(int(value) for value in cfg_get(cfg, "reference_steps", [0]))
    if reference_steps != (0,):
        raise ValueError("High-level policy sim2real requires reference_steps=[0]")
    recording_cfg = cfg_get(cfg, "recording", {}) or {}
    if bool(cfg_get(recording_cfg, "enabled", False)):
        raise ValueError("High-level policy recording is not supported in the initial runtime")

    calibration = HandCalibration.load()
    hands_cfg = cfg_get(cfg, "hands", {}) or {}
    if not bool(cfg_get(hands_cfg, "enabled", False)):
        raise ValueError("High-level policy action[36:48] requires hands.enabled=true")
    if str(cfg_get(hands_cfg, "driver", "")).strip().lower() != "linkerhand_o6":
        raise ValueError("High-level policy requires hands.driver=linkerhand_o6")
    hand_config = parse_linkerhand_o6_config(cfg)
    if len(hand_config.sides) != 2 or set(hand_config.sides) != {"left", "right"}:
        raise ValueError("High-level policy requires hands.sides=[left, right]")
    if tuple(float(value) for value in hand_config.open_pose) != calibration.open_raw:
        raise ValueError("LinkerHand O6 open_pose does not match hand_calibration.json")
    if tuple(float(value) for value in hand_config.close_pose) != calibration.close_raw:
        raise ValueError("LinkerHand O6 close_pose does not match hand_calibration.json")

    neck_cfg = parse_neck_config(cfg)
    if not neck_cfg.enabled or neck_cfg.driver != "openneck":
        raise ValueError("High-level policy action[48:50] requires neck.enabled=true and driver=openneck")


def _run_high_level_policy_client_worker(
    cfg: dict[str, Any], endpoints: Sim2RealIpcEndpoints, stop_event: MpEvent
) -> None:
    def _main() -> None:
        HighLevelPolicyWorker(cfg, endpoints, stop_event).run()

    _worker_loop("high_level_policy", cfg, _main)


def _run_high_level_policy_camera_worker(
    cfg: dict[str, Any], endpoints: Sim2RealIpcEndpoints, stop_event: MpEvent
) -> None:
    def _main() -> None:
        camera_cfg = parse_high_level_policy_camera_config(cfg)
        runtime_cfg = _mp_cfg(cfg)
        publisher = ZmqPublisher(endpoints.video_pub)
        command_sub = LatestSubscriber(endpoints.command_pub, COMMAND_TOPIC)
        writer = SharedFrameRingWriter(
            shape=(camera_cfg.height, camera_cfg.width, 3),
            dtype=np.uint8,
            slots=int(cfg_get(runtime_cfg, "video_slots", 3)),
        )
        pipeline: Any | None = None
        try:
            if camera_cfg.source == "realsense":
                try:
                    import pyrealsense2 as rs
                except ImportError as exc:
                    raise RuntimeError(
                        "RealSense high-level-policy camera requires pyrealsense2"
                    ) from exc
                pipeline = rs.pipeline()
                rs_config = rs.config()
                if camera_cfg.device is not None:
                    rs_config.enable_device(camera_cfg.device)
                rs_config.enable_stream(
                    rs.stream.color,
                    camera_cfg.width,
                    camera_cfg.height,
                    rs.format.rgb8,
                    camera_cfg.fps,
                )
                pipeline.start(rs_config)
            period_s = 1.0 / float(camera_cfg.fps)
            test_frame_index = 0
            camera_stalled = False
            while not stop_event.is_set():
                command = command_sub.recv_latest()
                if isinstance(command, CommandPacket) and command.command == "shutdown":
                    break
                started_s = time.monotonic()
                if pipeline is None:
                    frame = _test_pattern(
                        camera_cfg.height,
                        camera_cfg.width,
                        test_frame_index,
                    )
                    test_frame_index += 1
                else:
                    try:
                        frames = pipeline.wait_for_frames(timeout_ms=1000)
                    except RuntimeError as exc:
                        if not camera_stalled:
                            operator_logger.warning(
                                "High-level policy RealSense stalled: %s", exc
                            )
                        camera_stalled = True
                        continue
                    color = frames.get_color_frame()
                    if not color:
                        if not camera_stalled:
                            operator_logger.warning(
                                "High-level policy RealSense returned no color frame"
                            )
                        camera_stalled = True
                        continue
                    camera_stalled = False
                    frame = np.ascontiguousarray(
                        np.asanyarray(color.get_data()),
                        dtype=np.uint8,
                    )
                timestamp_s = time.monotonic()
                descriptor = writer.write(frame, timestamp_s=timestamp_s)
                publisher.publish(VIDEO_TOPIC, descriptor)
                if pipeline is None:
                    elapsed_s = time.monotonic() - started_s
                    if elapsed_s < period_s:
                        time.sleep(period_s - elapsed_s)
        finally:
            if pipeline is not None:
                pipeline.stop()
            writer.close(unlink=True)
            command_sub.close()
            publisher.close()

    _worker_loop("camera", cfg, _main)


def _test_pattern(height: int, width: int, frame_index: int) -> np.ndarray:
    x = np.linspace(0, 255, width, dtype=np.uint8)
    y = np.linspace(0, 255, height, dtype=np.uint8)[:, None]
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = x[None, :]
    frame[:, :, 1] = y
    frame[:, :, 2] = np.uint8(frame_index % 256)
    return frame


def _policy_target_action(target: HighLevelPolicyTargetPacket) -> np.ndarray:
    action = np.asarray(target.action, dtype=np.float32).reshape(-1)
    if action.shape != (50,) or not np.all(np.isfinite(action)):
        raise ValueError("High-level policy hardware worker received an invalid 50D target")
    return action


def _policy_target_is_current(
    target: object,
    mode: ModeStatePacket | None,
    *,
    last_target_seq: int,
    max_age_s: float,
    now_s: float | None = None,
) -> bool:
    if not isinstance(target, HighLevelPolicyTargetPacket):
        return False
    if mode is None or mode.mode != "policy" or mode.policy_paused:
        return False
    if mode.policy_session_id is None or target.session_id != mode.policy_session_id:
        return False
    if (
        not isinstance(target.seq, int)
        or isinstance(target.seq, bool)
        or target.seq <= last_target_seq
    ):
        return False
    current_s = time.monotonic() if now_s is None else float(now_s)
    age_s = current_s - float(target.timestamp_s)
    return bool(np.isfinite(age_s) and 0.0 <= age_s <= float(max_age_s))


def _apply_policy_hand_target(
    device: LinkerHandO6Device,
    target: HighLevelPolicyTargetPacket,
    calibration: HandCalibration,
) -> None:
    action = _policy_target_action(target)
    device.send_pose(
        "left",
        closure_to_o6_pose(action[36:42], calibration),
        reason="policy",
    )
    device.send_pose(
        "right",
        closure_to_o6_pose(action[42:48], calibration),
        reason="policy",
    )


def _apply_policy_neck_target(device: Any, target: HighLevelPolicyTargetPacket) -> None:
    action = _policy_target_action(target)
    device.move_deg(float(action[48]), float(action[49]))


def _run_high_level_policy_hand_worker(
    cfg: dict[str, Any], endpoints: Sim2RealIpcEndpoints, stop_event: MpEvent
) -> None:
    def _main() -> None:
        config = parse_linkerhand_o6_config(cfg)
        device = LinkerHandO6Device(config)
        calibration = HandCalibration.load()
        target_sub = LatestSubscriber(
            endpoints.high_level_policy_control_pub,
            HIGH_LEVEL_POLICY_TARGET_TOPIC,
        )
        mode_sub = LatestSubscriber(endpoints.mode_pub, MODE_TOPIC)
        command_sub = LatestSubscriber(endpoints.command_pub, COMMAND_TOPIC)
        latest_mode: ModeStatePacket | None = None
        last_target_seq = -1
        was_in_policy = False
        sleep_s = 1.0 / max(float(cfg_get(_mp_cfg(cfg), "hand_worker_hz", 120.0)), 1.0)
        try:
            device.connect()
            while not stop_event.is_set():
                command = command_sub.recv_latest()
                if isinstance(command, CommandPacket) and command.command == "shutdown":
                    break
                mode = mode_sub.recv_latest()
                if isinstance(mode, ModeStatePacket):
                    latest_mode = mode
                in_policy = bool(latest_mode is not None and latest_mode.mode == "policy")
                if was_in_policy and not in_policy:
                    device.open_all(force=True, reason="policy-inactive")
                was_in_policy = in_policy
                target = target_sub.recv_latest()
                if _policy_target_is_current(
                    target,
                    latest_mode,
                    last_target_seq=last_target_seq,
                    max_age_s=config.frame_timeout_s,
                ):
                    _apply_policy_hand_target(device, target, calibration)
                    last_target_seq = int(target.seq)
                time.sleep(sleep_s)
        finally:
            try:
                device.close()
            finally:
                target_sub.close()
                mode_sub.close()
                command_sub.close()

    _worker_loop("policy_hand", cfg, _main)


def _run_high_level_policy_neck_worker(
    cfg: dict[str, Any], endpoints: Sim2RealIpcEndpoints, stop_event: MpEvent
) -> None:
    def _main() -> None:
        config = parse_neck_config(cfg)
        device = build_neck_device(config)
        target_sub = LatestSubscriber(
            endpoints.high_level_policy_control_pub,
            HIGH_LEVEL_POLICY_TARGET_TOPIC,
        )
        mode_sub = LatestSubscriber(endpoints.mode_pub, MODE_TOPIC)
        command_sub = LatestSubscriber(endpoints.command_pub, COMMAND_TOPIC)
        latest_mode: ModeStatePacket | None = None
        last_target_seq = -1
        was_in_policy = False
        sleep_s = 1.0 / max(config.rate_hz, 1.0)
        try:
            device.connect()
            if config.center_on_start:
                device.center()
            while not stop_event.is_set():
                command = command_sub.recv_latest()
                if isinstance(command, CommandPacket) and command.command == "shutdown":
                    break
                mode = mode_sub.recv_latest()
                if isinstance(mode, ModeStatePacket):
                    latest_mode = mode
                in_policy = bool(latest_mode is not None and latest_mode.mode == "policy")
                if was_in_policy and not in_policy:
                    device.center()
                was_in_policy = in_policy
                target = target_sub.recv_latest()
                if _policy_target_is_current(
                    target,
                    latest_mode,
                    last_target_seq=last_target_seq,
                    max_age_s=config.frame_timeout_s,
                ):
                    _apply_policy_neck_target(device, target)
                    last_target_seq = int(target.seq)
                time.sleep(sleep_s)
        finally:
            try:
                device.center()
                if config.release_on_shutdown:
                    device.release_torque()
            finally:
                device.close()
                target_sub.close()
                mode_sub.close()
                command_sub.close()

    _worker_loop("policy_neck", cfg, _main)
