#!/usr/bin/env python3
"""t02_e2e.py — 原型闭环验证（无需相机）：

1. 合成结构源（移动渐变+白条+帧号块）2560x720@30 连续编码 N 帧；
2. 每帧记 E = encode() 全路径（BGRx 转换 + 7.37MB 管道写 + 子进程编码 + AU 读回），
   即 pacer 预算公式的硬编 E 真值（t01 同进程 10.7ms 的 IPC 补全版）；
3. 解码闭环：AU 流喂 av h264 解码器，帧数对账 + 帧号块解码比对（量化「可看画面」）；
4. force-IDR 中流生效验证（frame N/2 处请求 IDR，查该 AU 含 nal type 5）；
5. 落盘 .h264 流 + PNG 样帧供人工目检。

跑法（Jetson，teleimager env）：python t02_e2e.py [--frames 300] [--bitrate 4000000]
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nvenc_wrapper import NvencSubprocessEncoder, nal_types, fmt_stats

W, H, FPS = 2560, 720, 30
COUNTER_BITS = 16  # 帧号块位数（8x2 黑白块，左上角）


def make_frame(i: int) -> np.ndarray:
    """结构源：水平移动渐变 + 移动白条 + 16-bit 帧号块。每帧唯一（可解码回读对账）。"""
    x = np.arange(W, dtype=np.float32)
    b = (127 * np.sin(x * 0.015 + i * 0.13) + 128).astype(np.uint8)
    g = (127 * np.sin(x * 0.011 + i * 0.17 + 2.1) + 128).astype(np.uint8)
    r = (127 * np.sin(x * 0.019 + i * 0.11 + 4.2) + 128).astype(np.uint8)
    f = np.empty((H, W, 3), dtype=np.uint8)
    f[:, :, 0] = b
    f[:, :, 1] = g
    f[:, :, 2] = r
    bar = (i * 43) % (W - 64)
    f[:, bar:bar + 64] = 255
    for bit in range(COUNTER_BITS):
        y0 = 16 if bit < 8 else 64
        x0 = 16 + (bit % 8) * 48
        f[y0:y0 + 32, x0:x0 + 32] = 0 if (i >> bit) & 1 else 255
    return f


def read_counter(frame: np.ndarray) -> int:
    """从解码帧读回帧号块（中心 4x4 取多数决）。"""
    val = 0
    for bit in range(COUNTER_BITS):
        y0 = 16 if bit < 8 else 64
        x0 = 16 + (bit % 8) * 48
        blk = frame[y0 + 14:y0 + 18, x0 + 14:x0 + 18]
        if blk.mean() < 128:  # 黑 = 1
            val |= 1 << bit
    return val


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--bitrate", type=int, default=4_000_000)
    ap.add_argument("--format", choices=["BGRx", "I420"], default="BGRx",
                    help="传输格式实验：I420 管道字节 -62%%")
    ap.add_argument("--fps-pacing", action="store_true",
                    help="按 30fps 节拍喂帧（默认尽快连发，测纯往返）")
    ap.add_argument("--tag", default="e2e")
    args = ap.parse_args()

    import av  # 延迟导入：仅 e2e 需要解码器

    enc = NvencSubprocessEncoder(W, H, FPS, bitrate=args.bitrate, format=args.format)
    idr_frame = args.frames // 2  # 中流 force-IDR 验证点
    aus, idr_au_idx, first_e_ms = [], None, None
    t_start = time.perf_counter()
    try:
        enc.start()  # try 内：失败也要走 stop() 清子进程
        print(f"[e2e] child ready in {enc.spawn_s*1000:.0f} ms, force_idr_prop={enc.force_idr_prop!r}")
        for i in range(args.frames):
            f = make_frame(i)
            force = (i == 0) or (i == idr_frame)
            au = enc.encode(f, force_keyframe=force)
            if first_e_ms is None:
                first_e_ms = enc.last_encode_s * 1000.0
            if i == idr_frame:
                idr_au_idx = len(aus)
            aus.append(au)
            if args.fps_pacing:
                next_t = t_start + (i + 1) / FPS
                delay = next_t - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
    finally:
        run_s = time.perf_counter() - t_start
        st = enc.stats
        enc.stop()

    # ---- 延迟报告（首帧单列，稳态不含首帧） ----
    print(f"\n[e2e] first-frame E: {first_e_ms:.1f} ms (含 NVMEDIA 会话建立)")
    print(f"[e2e] steady E(total):   {fmt_stats(st['encode_s'][1:])}")
    print(f"[e2e]   conv  BGR->BGRx: {fmt_stats(st['conv_s'][1:])}")
    print(f"[e2e]   write pipe+hdr:  {fmt_stats(st['write_s'][1:])}")
    print(f"[e2e]   wait  child+AU:  {fmt_stats(st['wait_s'][1:])}")
    print(f"[e2e] wall {run_s:.1f}s, {st['frames']} frames, "
          f"{st['au_bytes']*8/max(run_s,1e-9)/1e6:.2f} Mbit/s avg, restarts={st['restarts']}")

    # ---- AU 结构检查 ----
    n0 = nal_types(aus[0])
    print(f"[e2e] first AU nal types {n0} (期望含 7 SPS / 8 PPS / 5 IDR)")
    if idr_au_idx is not None and enc.force_idr_prop:
        nidr = nal_types(aus[idr_au_idx])
        ok = 5 in nidr
        print(f"[e2e] force-IDR @frame {idr_frame}: AU nal types {nidr} -> "
              f"{'IDR PRESENT (force-IDR 生效)' if ok else 'NO IDR (force-IDR 未生效!)'}")
    elif idr_au_idx is not None:
        print(f"[e2e] force-IDR @frame {idr_frame}: 子进程无该属性，跳过检查（记 03 票）")

    # ---- 解码闭环 ----
    dec = av.CodecContext.create("h264", "r")
    frames = []
    for au in aus:
        try:
            frames.extend(dec.decode(av.Packet(au)))
        except Exception as e:
            print(f"[e2e] decode error on one AU: {e}")
    print(f"[e2e] decoded {len(frames)}/{args.frames} frames ({frames[0].width}x{frames[0].height})"
          if frames else "[e2e] decoded 0 frames!")

    match, mismatch = 0, []
    for j, fr in enumerate(frames):
        arr = fr.to_ndarray(format="bgr24")
        got = read_counter(arr)
        if got == j:
            match += 1
        else:
            mismatch.append((j, got))
            if len(mismatch) <= 5:
                print(f"[e2e]   counter mismatch: frame {j} decoded as {got}")
    print(f"[e2e] frame-counter check: {match}/{len(frames)} exact")

    # ---- 落盘 ----
    outdir = os.path.dirname(os.path.abspath(__file__))
    stream_path = os.path.join(outdir, f"t02_{args.tag}.h264")
    with open(stream_path, "wb") as fh:
        fh.write(b"".join(aus))
    print(f"[e2e] annexb stream -> {stream_path}")
    try:
        import cv2
        for j in (0, min(idr_frame or 0, len(frames) - 1), len(frames) - 1):
            if 0 <= j < len(frames):
                p = os.path.join(outdir, f"t02_{args.tag}_f{j:04d}.png")
                cv2.imwrite(p, frames[j].to_ndarray(format="bgr24"))
        print(f"[e2e] sample PNGs -> {outdir}")
    except ImportError:
        print("[e2e] cv2 不可用，跳过 PNG")
    print("DONE")


if __name__ == "__main__":
    main()
