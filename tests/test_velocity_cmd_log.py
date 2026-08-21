# tests/test_velocity_cmd_log.py
import json

import numpy as np

from teleopit.sim2real.mp.cmd_log import VelocityCmdLogger


def test_log_writes_jsonl_lines(tmp_path) -> None:
    path = tmp_path / "cmd.jsonl"
    logger = VelocityCmdLogger(str(path))
    logger.log(cmd=np.array([0.6, 0, 0, 0, 0, 0.0]), estop_state="inactive", mode="velocity", muted=False)
    logger.log(cmd=np.zeros(6), estop_state="latched", mode="velocity", muted=True)
    logger.close()

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    np.testing.assert_allclose(lines[0]["cmd"], [0.6, 0.0, 0.0, 0.0, 0.0, 0.0], atol=1e-6)
    assert lines[0]["estop"] == "inactive"
    assert lines[1]["muted"] is True


def test_none_path_is_a_noop() -> None:
    logger = VelocityCmdLogger(None)
    logger.log(cmd=np.zeros(6), estop_state="inactive", mode="velocity", muted=False)
    logger.close()  # 不抛即过
