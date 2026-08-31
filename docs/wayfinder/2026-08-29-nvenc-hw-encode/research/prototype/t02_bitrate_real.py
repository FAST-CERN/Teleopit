#!/usr/bin/env python3
"""t02_bitrate_real.py — 降档欠冲真实内容复验（t01 §1.2 遗留项）。

订阅 zed_xr_bridge 的 ZMQ IPC（与 image_server ZEDBridgeCamera 同款 SUB+CONFLATE，
44 字节 FrameHeaderV1 + BGR8 SBS），真实内容连续编码，1s 窗口码率轨迹：

  t=8s  SET->2M（降档：满熵 snow 下 t01 只收敛到 ~65%，真实内容复验点）
  t=18s SET->6M（升档对照）
  --force-idr-on-set: 每次设值后下一帧 force-IDR（备选缓解的 A/B 开关）

顺带采集真实内容下的每帧 E 分布（t03 重算摊平窗口 W 的输入）。

前置：仅起 zed_xr_bridge 二进制（相机发布器），teleimager-server 保持停止。
跑法：<env_python> t02_bitrate_real.py [--endpoint ipc:///tmp/zed_xr_head.ipc]
     [--force-idr-on-set] [--duration 28]
"""
import argparse
import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nvenc_wrapper import NvencSubprocessEncoder, fmt_stats

_HDR = struct.Struct("<4sHHQQIIIBBHI")  # C++ FrameHeaderV1，44 字节
W, H, FPS = 2560, 720, 30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="ipc:///tmp/zed_xr_head.ipc")
    ap.add_argument("--duration", type=float, default=28.0)
    ap.add_argument("--set-low", type=float, default=8.0)
    ap.add_argument("--set-high", type=float, default=18.0)
    ap.add_argument("--low", type=int, default=2_000_000)
    ap.add_argument("--high", type=int, default=6_000_000)
    ap.add_argument("--start", type=int, default=4_000_000)
    ap.add_argument("--force-idr-on-set", action="store_true")
    ap.add_argument("--format", choices=["BGRx", "I420"], default="BGRx")
    ap.add_argument("--save-prefix", default=None,
                    help="存 AU 流到 <prefix>.h264 并解码抽查 PNG（真实内容可看画面证据）")
    ap.add_argument("--tag", default="real")
    args = ap.parse_args()

    import zmq

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.SUB)
    sock.setsockopt(zmq.SUBSCRIBE, b"")
    sock.setsockopt(zmq.RCVHWM, 1)
    sock.setsockopt(zmq.CONFLATE, 1)
    sock.setsockopt(zmq.RCVTIMEO, 500)
    sock.connect(args.endpoint)
    print(f"[real] subscribed {args.endpoint}; waiting for bridge frames ...")
    first = None
    while first is None or len(first) < _HDR.size:  # RCVTIMEO 每次生效，循环到首帧
        try:
            first = sock.recv()
        except zmq.Again:
            continue

    enc = NvencSubprocessEncoder(W, H, FPS, bitrate=args.start, format=args.format)
    enc.start()
    print(f"[real] child ready, force_idr_prop={enc.force_idr_prop!r}, "
          f"force_idr_on_set={args.force_idr_on_set}, format={args.format}")

    events = []  # (t, label)
    aus = [] if args.save_prefix else None
    win_bytes, win_t0, win_frames, gap_frames = 0, None, 0, 0
    t0 = time.perf_counter()
    next_tick = t0
    force_next = False
    try:
        while True:
            now = time.perf_counter()
            el = now - t0
            if el >= args.duration:
                break
            # 事件调度
            if el >= args.set_low and len(events) == 0:
                enc.set_bitrate(args.low)
                events.append((el, f"SET->{args.low//1000}k"))
                if args.force_idr_on_set:
                    force_next = True
            elif el >= args.set_high and len(events) == 1:
                enc.set_bitrate(args.high)
                events.append((el, f"SET->{args.high//1000}k"))
                if args.force_idr_on_set:
                    force_next = True
            # 30fps 节拍
            next_tick += 1.0 / FPS
            delay = next_tick - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            try:
                msg = sock.recv()
            except zmq.Again:
                gap_frames += 1
                continue
            if len(msg) < _HDR.size:
                gap_frames += 1
                continue
            h = _HDR.unpack_from(msg, 0)
            w, hh, stride, ch, pf, payload = h[5], h[6], h[7], h[8], h[9], h[11]
            if not (h[0] == b"ZED1" and ch == 3 and pf == 1 and payload == stride * hh):
                gap_frames += 1
                continue
            bgr = np.frombuffer(msg, dtype=np.uint8, count=hh * w * 3, offset=_HDR.size)
            bgr = bgr.reshape(hh, w, 3)
            au = enc.encode(bgr, force_keyframe=force_next)
            force_next = False
            if aus is not None:
                aus.append(au)
            au_len = enc.stats["au_bytes"]
            if win_t0 is None:
                win_t0 = time.perf_counter()
                au_base = au_len
            win_frames += 1
            now = time.perf_counter()
            if now - win_t0 >= 1.0:
                mbps = (au_len - au_base) * 8 / (now - win_t0) / 1e6
                ev = "  " + ";".join(f"{lb}@{te:.0f}s" for te, lb in events[-1:]) \
                    if events and events[-1][0] > now - t0 - 1.0 else ""
                print(f"[t={now - t0:5.1f}s] {mbps:7.2f} Mbit/s  ({win_frames} f){ev}")
                win_t0, au_base, win_frames = now, au_len, 0
    finally:
        st = enc.stats
        enc.stop()
        sock.close(linger=0)

    print(f"\n[real] gaps(no frame): {gap_frames}")
    print(f"[real] real-content E(total): {fmt_stats(st['encode_s'][1:])}")
    print(f"[real]   conv BGR->BGRx:      {fmt_stats(st['conv_s'][1:])}")
    print(f"[real]   write pipe:          {fmt_stats(st['write_s'][1:])}")
    print(f"[real]   wait child+AU:       {fmt_stats(st['wait_s'][1:])}")
    print(f"[real] restarts={st['restarts']}, force_idr_on_set={args.force_idr_on_set}")

    if aus:
        import av
        with open(args.save_prefix + ".h264", "wb") as fh:
            fh.write(b"".join(aus))
        dec = av.CodecContext.create("h264", "r")
        frames = []
        for au in aus:
            try:
                frames.extend(dec.decode(av.Packet(au)))
            except Exception as e:
                print(f"[real] decode error: {e}")
        print(f"[real] saved {len(aus)} AUs -> {args.save_prefix}.h264, "
              f"decoded {len(frames)} frames")
        try:
            import cv2
            for j in (0, len(frames) // 2, len(frames) - 1):
                if 0 <= j < len(frames):
                    cv2.imwrite(f"{args.save_prefix}_f{j:04d}.png",
                                frames[j].to_ndarray(format="bgr24"))
            print(f"[real] PNGs -> {args.save_prefix}_f*.png")
        except ImportError:
            pass
    print("DONE")


if __name__ == "__main__":
    main()
