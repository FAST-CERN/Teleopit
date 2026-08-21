# teleopit/sim2real/mp/cmd_log.py
"""Per-step jsonl command log for the real VELOCITY mode (bsi-realhw-07).

The acceptance timing table (intent->cmd, E->cmd0, joystick-preemption
cycles) is derived offline from this file; LowState has no base_lin_vel, so
the merged cmd stream is the authoritative observable.
"""
from __future__ import annotations

import json
import time
from typing import Any

import numpy as np


class VelocityCmdLogger:
    """Append one JSON line per policy step; disabled when path is None."""

    def __init__(self, path: str | None) -> None:
        self._path = path
        self._fh: Any = None
        if path:
            self._fh = open(path, "a", encoding="utf-8")

    def log(self, *, cmd: np.ndarray, estop_state: str, mode: str, muted: bool) -> None:
        if self._fh is None:
            return
        record = {
            "t": time.monotonic(),
            "cmd": [float(v) for v in np.asarray(cmd, dtype=np.float32).reshape(-1)[:6]],
            "estop": str(estop_state),
            "mode": str(mode),
            "muted": bool(muted),
        }
        self._fh.write(json.dumps(record) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
