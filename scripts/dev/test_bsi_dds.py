#!/usr/bin/env python3
"""Smoke-test the BSI_DDSInterface submodule (third_party/BSI_DDSInterface).

Checks the submodule is checked out, imports ``bsi_dds`` from it, and runs
a short local DDS pub/sub loopback on domain 0. Optional hardware-free
verification for the BSI discrete-command link; see
``docs/knowledge/repo-guide.md`` for submodule checkout prerequisites.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BSI_PKG_PATH = REPO_ROOT / "third_party" / "BSI_DDSInterface"
if BSI_PKG_PATH.exists():
    sys.path.insert(0, str(BSI_PKG_PATH))

import bsi_dds  # noqa: E402
from bsi_dds import DiscreteCommandPublisher, DiscreteCommandSubscriber  # noqa: E402
from bsi_dds.protocol import SILENCE_TIMEOUT_S, TOPIC_CMD_DISCRETE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration-s", type=float, default=3.0, help="loopback duration"
    )
    args = parser.parse_args()

    print(f"bsi_dds {bsi_dds.__version__} from {bsi_dds.__file__}")
    print(f"topic {TOPIC_CMD_DISCRETE}, silence {SILENCE_TIMEOUT_S}s -> IDLE")

    sub = DiscreteCommandSubscriber()
    pub = DiscreteCommandPublisher()
    received = 0
    try:
        time.sleep(0.5)  # discovery settle
        deadline = time.monotonic() + args.duration_s
        seq = 0
        while time.monotonic() < deadline:
            pub.publish(seq % 4)
            seq += 1
            for _ in sub.reader.take():
                received += 1
            time.sleep(0.1)
    finally:
        pub.close()
        sub.close()

    expected = int(args.duration_s * 10)
    print(f"received {received}/{expected} samples")
    if received == 0:
        print("FAIL: no loopback traffic")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
