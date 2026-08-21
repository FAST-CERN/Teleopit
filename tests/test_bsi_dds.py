"""BSI_DDSInterface submodule smoke tests.

Skips cleanly when the submodule is not checked out (fresh clone without
``git submodule update --init``) or cyclonedds is not installed, so the
main suite never goes red over an optional component. Hardware-free: only
protocol constants and imports are checked here; the DDS loopback lives in
the submodule's own test suite (``pytest third_party/BSI_DDSInterface``).
"""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BSI_SUBMODULE = _REPO_ROOT / "third_party" / "BSI_DDSInterface"


def _bsi_dds_available() -> bool:
    if not (_BSI_SUBMODULE / "bsi_dds" / "__init__.py").exists():
        return False
    try:
        import cyclonedds  # noqa: F401
    except ImportError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _bsi_dds_available(),
    reason="BSI_DDSInterface submodule not checked out or cyclonedds missing",
)


@pytest.fixture()
def bsi_dds():
    import sys

    sys.path.insert(0, str(_BSI_SUBMODULE))
    try:
        import bsi_dds

        yield bsi_dds
    finally:
        sys.path.remove(str(_BSI_SUBMODULE))


def test_protocol_constants_match_wayfinder_decision(bsi_dds):
    # Locked by bsi-dds-01: IDLE=0 fail-safe, bsi/cmd_discrete, domain 0,
    # 10Hz stream, deadline 0.5s, 1s silence -> IDLE.
    assert bsi_dds.CMD_IDLE == 0
    assert bsi_dds.TOPIC_CMD_DISCRETE == "bsi/cmd_discrete"
    assert bsi_dds.DEFAULT_DOMAIN_ID == 0
    assert bsi_dds.MIN_RATE_HZ == 10.0
    assert bsi_dds.DEADLINE_S == 0.5
    assert bsi_dds.SILENCE_TIMEOUT_S == 1.0


def test_publisher_subscriber_importable(bsi_dds):
    assert hasattr(bsi_dds, "DiscreteCommandPublisher")
    assert hasattr(bsi_dds, "DiscreteCommandSubscriber")


def test_enum_values(bsi_dds):
    from bsi_dds.idl import DiscreteCommand

    assert [c.value for c in DiscreteCommand] == [0, 1, 2, 3]
