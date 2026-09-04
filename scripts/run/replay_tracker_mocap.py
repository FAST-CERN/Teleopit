"""Replay a recorded tracker JSONL into the mocap skeleton viewer (mocap map t08).

Reads a receiver recording (``{"type": "tracking", ...}`` envelopes), drives the
unmodified ``Pico4InputProvider`` body path through :class:`TrackerReplayBridge`
(arm_source=tracker synthesis -> coordinate transform -> ground alignment), and
renders the synthesized human skeleton in the same MuJoCo "Mocap Input" viewer
the sim loop lights up — no device, no sim, no policy.

Usage::

    python scripts/run/replay_tracker_mocap.py <recording.jsonl> [--speed 1.0]
        [--no-loop] [--synth-yaml offsets.yaml] [--win-x 50 --win-y 50]

``--synth-yaml`` takes a flat YAML of SynthConfig fields for mount-offset /
anthropometry sweeps, e.g. ``tracker_offset: {left: [0, 0, -0.02]}``.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
import time
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np

from teleopit.inputs.pico4_provider import Pico4InputProvider
from teleopit.inputs.tracker_replay import TrackerReplayBridge
from teleopit.sim.viewer_subprocess import mocap_viewer_proc

STATS_INTERVAL_S = 2.0
RENDER_HZ = 30.0


class _RecordingBridgeFactory:
    """Callable bridge_cls that keeps a handle on the constructed bridge."""

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self.instance: TrackerReplayBridge | None = None

    def __call__(self, **provider_kwargs: Any) -> TrackerReplayBridge:
        self.instance = TrackerReplayBridge(**self._kwargs, **provider_kwargs)
        return self.instance


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("recording", type=Path, help="receiver recording JSONL to replay")
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed multiplier (default 1.0)")
    parser.add_argument("--no-loop", action="store_true", help="exit after one pass instead of looping")
    parser.add_argument(
        "--synth-yaml",
        type=Path,
        default=None,
        help="YAML with SynthConfig fields (tracker_offset, hold_s, ...) overriding defaults",
    )
    parser.add_argument("--win-x", type=int, default=50, help="viewer window x (default 50)")
    parser.add_argument("--win-y", type=int, default=50, help="viewer window y (default 50)")
    parser.add_argument(
        "--max-duration",
        type=float,
        default=0.0,
        help="stop after this many seconds of playback (0 = run until window closed)",
    )
    return parser.parse_args(argv)


def _load_synth_config(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    import yaml

    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"--synth-yaml must contain a mapping of SynthConfig fields, got {type(data)!r}")
    return data


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if not args.recording.is_file():
        print(f"recording not found: {args.recording}", file=sys.stderr)
        raise SystemExit(1)
    synth_config = _load_synth_config(args.synth_yaml)

    factory = _RecordingBridgeFactory(
        path=args.recording,
        speed=args.speed,
        loop=not args.no_loop,
    )
    provider = Pico4InputProvider(
        arm_source="tracker",
        tracker_synth_config=synth_config,
        timeout=5.0,
        pause_button=None,
        arms_button=None,
        bridge_cls=factory,
    )
    bridge = factory.instance
    assert bridge is not None

    bone_names = provider.bone_names
    n_bones = len(bone_names)
    pos_arr = mp.Array("d", n_bones * 3)
    shutdown = mp.Event()
    alive = mp.Value("i", 0)
    viewer_proc = mp.Process(
        target=mocap_viewer_proc,
        args=(list(provider.bone_parents.astype(int)), pos_arr, n_bones, shutdown, alive, args.win_x, args.win_y),
        daemon=True,
    )
    viewer_proc.start()

    loop_label = "single pass" if args.no_loop else "loop"
    print(
        f"Replaying {args.recording.name}: {len(bridge)} tracking records, "
        f"speed={args.speed}x, {loop_label}"
    )
    if synth_config is not None:
        print(f"Synth overrides: {synth_config}")
    print("Close the viewer window (or Ctrl+C) to stop.")

    started = time.monotonic()
    last_stats = started
    frames_drawn = 0
    try:
        deadline = started + args.max_duration if args.max_duration > 0.0 else None
        while viewer_proc.is_alive() and not shutdown.is_set():
            if provider.has_frame():
                human_frame, _timestamp_s, _seq = provider.get_frame_packet()
                pos_flat = np.zeros(n_bones * 3, dtype=np.float64)
                for i, bone in enumerate(bone_names):
                    if bone in human_frame:
                        pos_flat[i * 3:(i + 1) * 3] = human_frame[bone][0]
                with pos_arr.get_lock():
                    pos_arr[:n_bones * 3] = pos_flat.tolist()
                frames_drawn += 1
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                print("Max duration reached.")
                break
            if now - last_stats >= STATS_INTERVAL_S:
                last_stats = now
                try:
                    fps = provider.fps
                except Exception:
                    fps = float("nan")
                print(
                    f"t={now - started:6.1f}s  drawn={frames_drawn}  provider_fps={fps:5.1f}  "
                    f"pass={bridge.iteration + 1}"
                )
            time.sleep(1.0 / RENDER_HZ)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        shutdown.set()
        viewer_proc.join(timeout=3.0)
        if viewer_proc.is_alive():
            viewer_proc.terminate()
        provider.close()
        print(f"Done: {frames_drawn} frames drawn over {time.monotonic() - started:.1f}s.")


if __name__ == "__main__":
    main()
