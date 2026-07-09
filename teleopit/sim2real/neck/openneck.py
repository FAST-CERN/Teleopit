from __future__ import annotations

import logging
from typing import Protocol

from teleopit.sim2real.neck.config import NeckConfig

logger = logging.getLogger(__name__)


class NeckDevice(Protocol):
    def connect(self) -> None: ...

    def center(self) -> None: ...

    def release(self) -> None: ...

    def move_norm(self, yaw: float, pitch: float) -> None: ...

    def close(self) -> None: ...


class OpenNeckDevice:
    def __init__(self, config: NeckConfig) -> None:
        self._cfg = config
        self._context = None
        self._controller = None

    def connect(self) -> None:
        try:
            from openneck import OpenNeckController
        except ModuleNotFoundError as exc:
            raise ImportError(
                "openneck is required for neck.driver=openneck. "
                "Install with: pip install -e '.[openneck]'"
            ) from exc
        controller = OpenNeckController(
            config=self._cfg.config_path,
            port=self._cfg.port,
            enable_torque_on_connect=True,
        )
        entered = controller.__enter__()
        self._context = controller
        self._controller = controller if entered is None else entered
        logger.info("OpenNeck connected on port %s", getattr(self._controller, "port", self._cfg.port))

    def center(self) -> None:
        if self._controller is not None:
            self._controller.center(wait_s=0.5)

    def move_norm(self, yaw: float, pitch: float) -> None:
        if self._controller is not None:
            self._controller.move_norm(float(yaw), float(pitch))

    def release(self) -> None:
        if self._controller is None:
            return
        release = getattr(self._controller, "release", None)
        if callable(release):
            release()
            return
        disable_torque = getattr(self._controller, "disable_torque", None)
        if callable(disable_torque):
            disable_torque()

    def close(self) -> None:
        context = self._context
        controller = self._controller
        self._context = None
        self._controller = None
        close_error: BaseException | None = None
        if context is not None:
            exit_context = getattr(context, "__exit__", None)
            if callable(exit_context):
                try:
                    exit_context(None, None, None)
                    return
                except BaseException as exc:
                    close_error = exc
                    logger.exception("OpenNeck context exit failed; trying direct close")
        close_targets = [target for target in (controller, context) if target is not None]
        seen_target_ids: set[int] = set()
        direct_close_error: BaseException | None = None
        for target in close_targets:
            target_id = id(target)
            if target_id in seen_target_ids:
                continue
            seen_target_ids.add(target_id)
            close = getattr(target, "close", None)
            if callable(close):
                try:
                    close()
                except BaseException as exc:
                    direct_close_error = exc
                    logger.exception("OpenNeck direct close failed")
        if close_error is not None:
            if direct_close_error is not None:
                raise close_error from direct_close_error
            raise close_error
        if direct_close_error is not None:
            raise direct_close_error


class DryRunNeckDevice:
    def connect(self) -> None:
        logger.info("OpenNeck dry-run device active")

    def center(self) -> None:
        logger.info("OpenNeck dry-run center")

    def move_norm(self, yaw: float, pitch: float) -> None:
        logger.debug("OpenNeck dry-run command yaw=%.3f pitch=%.3f", yaw, pitch)

    def release(self) -> None:
        logger.info("OpenNeck dry-run release")

    def close(self) -> None:
        logger.info("OpenNeck dry-run closed")


def build_neck_device(config: NeckConfig) -> NeckDevice:
    if config.driver != "openneck":
        raise ValueError("Unsupported neck.driver={!r}; supported drivers: openneck".format(config.driver))
    if config.dry_run:
        return DryRunNeckDevice()
    return OpenNeckDevice(config)
