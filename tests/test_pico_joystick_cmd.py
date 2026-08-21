"""PicoJoystickProvider: pico sticks -> 6D twist with deadzone + disconnect-zero."""
from __future__ import annotations

import numpy as np

from teleopit.commands.pico_joystick import PicoJoystickProvider

_CMD_LIMITS = {"lin_vel_x": [-1.0, 2.0], "lin_vel_y": [-0.5, 0.5], "ang_vel_z": [-1.0, 1.0]}


class _State:
    def __init__(self, axis_x=0.0, axis_y=0.0, present=True):
        self.axis_x = float(axis_x)
        self.axis_y = float(axis_y)
        self.present = bool(present)
        self.raw = bool(present)


class _Snapshot:
    def __init__(self, left, right, timestamp_s=0.0, seq=0):
        self.left = left
        self.right = right
        self.timestamp_s = float(timestamp_s)
        self.seq = int(seq)


class _Provider:
    """Stands in for Pico4InputProvider."""

    def __init__(self, snapshot=None):
        self.snapshot = snapshot

    def get_controller_snapshot(self):
        return self.snapshot


def _provider(left=(0.0, 0.0), right=(0.0, 0.0), timestamp_s=0.0):
    return _Provider(_Snapshot(_State(*left), _State(*right), timestamp_s=timestamp_s))


def _clock():
    return 0.0  # Mock clock for consistent testing


def test_neutral_sticks_give_zero_twist():
    provider = PicoJoystickProvider(_provider(), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_deadzone_rejects_small_sticks():
    provider = PicoJoystickProvider(_provider(left=(0.14, 0.14)), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_deadzone_edge_is_zero():
    provider = PicoJoystickProvider(_provider(left=(0.15, -0.15)), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_left_stick_y_maps_lin_x_asymmetric_limits():
    provider = PicoJoystickProvider(_provider(left=(0.0, 1.0)), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd()[0], 2.0)
    provider = PicoJoystickProvider(_provider(left=(0.0, -1.0)), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd()[0], -1.0)


def test_left_stick_x_maps_lin_y():
    # Push RIGHT (+1) must strafe RIGHT (lin_y negative): Phase A keyboard
    # convention has lin_y>0 = left strafe, Unity stick +X = push right.
    provider = PicoJoystickProvider(_provider(left=(1.0, 0.0)), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd()[1], -0.5)
    provider = PicoJoystickProvider(_provider(left=(-1.0, 0.0)), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd()[1], 0.5)


def test_right_stick_x_maps_ang_z():
    # Push RIGHT (+0.8) must turn RIGHT (ang_z negative): ang_z>0 = CCW/left.
    provider = PicoJoystickProvider(_provider(right=(0.8, 0.0)), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd()[5], -0.8)
    provider = PicoJoystickProvider(_provider(right=(-0.8, 0.0)), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd()[5], 0.8)


def test_partial_stick_scales_linearly():
    provider = PicoJoystickProvider(_provider(left=(0.0, 0.5)), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd()[0], 1.0)


def test_no_snapshot_reads_zero():
    provider = PicoJoystickProvider(_Provider(None), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_disconnected_controllers_read_zero():
    provider = PicoJoystickProvider(_provider(), cmd_limits=_CMD_LIMITS, clock=_clock)
    provider._input_provider.snapshot = _Snapshot(_State(present=False), _State(present=False))
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_stale_snapshot_reads_zero():
    provider = PicoJoystickProvider(_provider(left=(0.0, 1.0)), cmd_limits=_CMD_LIMITS, clock=_clock)
    provider._input_provider.snapshot.timestamp_s = -10.0
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_missing_axis_attr_reads_zero():
    class _LegacyState:
        present = True
        # no axis_x/axis_y — pre-Task-2 snapshot shape

    provider = PicoJoystickProvider(
        _Provider(_Snapshot(_LegacyState(), _LegacyState())), cmd_limits=_CMD_LIMITS, clock=_clock
    )
    np.testing.assert_allclose(provider.get_cmd(), np.zeros(6, dtype=np.float32))


def test_default_cmd_limits_used_when_none():
    provider = PicoJoystickProvider(_provider(left=(0.0, 1.0)), clock=_clock)
    np.testing.assert_allclose(provider.get_cmd()[0], 2.0)


def test_reset_and_close_are_safe():
    provider = PicoJoystickProvider(_provider(left=(0.0, 1.0)), cmd_limits=_CMD_LIMITS, clock=_clock)
    provider.get_cmd()
    provider.reset()
    provider.close()
    assert provider.get_cmd().shape == (6,)


def test_stick_scale_cap_bounds_full_forward():
    """max_stick_scale caps the reachable stick envelope (operator fix 2026-08-20).

    Full-forward at cmd hi=2.0 m/s exceeds the Phase-A-validated safety
    envelope (joint-vel gate 12.0 rad/s was calibrated at 1.0 m/s; a 2.0 m/s
    gait trips it within seconds). Cap the scale so stick +1 reaches only
    the ratified 1.0 m/s while the builder clamp stays at the yaml limits.
    """
    provider = PicoJoystickProvider(
        _provider(left=(0.0, 1.0)), cmd_limits=_CMD_LIMITS, clock=_clock,
        max_stick_scale={"lin_vel_x": 0.5},
    )
    np.testing.assert_allclose(provider.get_cmd()[0], 1.0)  # 1.0 * 2.0 * 0.5
    provider = PicoJoystickProvider(
        _provider(left=(0.0, -1.0)), cmd_limits=_CMD_LIMITS, clock=_clock,
        max_stick_scale={"lin_vel_x": 0.5},
    )
    np.testing.assert_allclose(provider.get_cmd()[0], -0.5)  # -1 * 1.0 * 0.5


def test_stick_scale_cap_partial_stick_and_default_uncapped():
    provider = PicoJoystickProvider(
        _provider(left=(0.0, 0.5)), cmd_limits=_CMD_LIMITS, clock=_clock,
        max_stick_scale={"lin_vel_x": 0.5},
    )
    np.testing.assert_allclose(provider.get_cmd()[0], 0.5)  # half stick -> half of cap
    # Default: no cap dict -> full envelope (unchanged Phase A behavior).
    provider = PicoJoystickProvider(_provider(left=(0.0, 1.0)), cmd_limits=_CMD_LIMITS, clock=_clock)
    np.testing.assert_allclose(provider.get_cmd()[0], 2.0)
