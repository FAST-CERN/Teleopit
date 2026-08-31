#!/usr/bin/env python3
"""t02_crash.py — 子进程崩溃重启行为（重启->IDR->续流 语义雏形）。

合成源连续编码，frame K 处 os.kill(child, SIGKILL)：
  - gap 实测：kill -> 同帧 AU 返回（wrapper 内部重启+重发，上层无帧丢失）
  - 重启后首 AU 应含 SPS/PPS/IDR（新会话天然 IDR + insert-sps-pps）
  - 全流解码对账：解码帧数 = 发帧数，帧号块序列连续跨越重启点（续流语义）

跑法（Jetson）：python t02_crash.py [--frames 300] [--kill-at 120]
"""
import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nvenc_wrapper import NvencSubprocessEncoder, nal_types, fmt_stats
from t02_e2e import W, H, FPS, make_frame, read_counter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--kill-at", type=int, default=120)
    ap.add_argument("--bitrate", type=int, default=4_000_000)
    args = ap.parse_args()

    import av

    enc = NvencSubprocessEncoder(W, H, FPS, bitrate=args.bitrate)
    aus = []
    kill_reported = False
    t_kill = None
    try:
        enc.start()  # try 内：失败也要走 stop() 清子进程
        for i in range(args.frames):
            if i == args.kill_at and args.kill_at > 0:
                t_kill = time.perf_counter()
                os.kill(enc.proc.pid, signal.SIGKILL)
                print(f"[crash] frame {i}: SIGKILL child pid {enc.proc.pid}")
            au = enc.encode(make_frame(i), force_keyframe=(i == 0))
            if t_kill is not None and not kill_reported:
                kill_reported = True
                gap = enc.last_restart_gap_s
                gap_s = f", wrapper restart->AU {gap*1000:.0f} ms" if gap else ""
                print(f"[crash] kill -> same-frame AU returned "
                      f"{((time.perf_counter()-t_kill)*1000):.0f} ms{gap_s}")
            aus.append(au)
    finally:
        st = enc.stats
        enc.stop()

    print(f"\n[crash] restarts={st['restarts']} (期望 1), steady E: {fmt_stats(st['encode_s'][1:])}")
    # 重启点前后 AU 结构
    k = args.kill_at
    if 0 < k < len(aus):
        pre, post = nal_types(aus[k - 1]), nal_types(aus[k])
        resumed = {7, 8, 5} <= set(post)
        print(f"[crash] AU[{k-1}] (pre-restart)  nal {pre}")
        print(f"[crash] AU[{k}]  (post-restart) nal {post} -> "
              f"{'SPS+PPS+IDR ✓ 续流语义成立' if resumed else '缺失关键 NAL!'}")

    # 全流解码对账（跨越重启点不重置解码器）
    dec = av.CodecContext.create("h264", "r")
    frames = []
    for au in aus:
        try:
            frames.extend(dec.decode(av.Packet(au)))
        except Exception as e:
            print(f"[crash] decode error: {e}")
    ok = sum(1 for j, fr in enumerate(frames) if read_counter(fr.to_ndarray(format="bgr24")) == j)
    print(f"[crash] decoded {len(frames)}/{args.frames}, counter-exact {ok}/{len(frames)} "
          f"(连续跨越重启点 = 续流)")
    print("DONE")


if __name__ == "__main__":
    main()
