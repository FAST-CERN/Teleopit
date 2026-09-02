#!/usr/bin/env python3
"""Low-entropy synthetic source for the sbs-1080p decode gate (ticket 02).

Attempt 1 used pure random noise, which (a) drove the encoder to its QP floor
(AU ~440KB/frame at 3840x1080 = ~100Mbps class -- WiFi tore it apart, hence
the garbled screen) and (b) costs too much numpy per frame at 4.1MP to sustain
30fps. This variant precomputes a static, compressible stereo scene once
(gradient sky + soft blobs) and per frame only memcpy's it and moves a
high-contrast patch in lockstep in both eyes: cheap enough for 30fps and
lands near the CBR target instead of the QP floor. FrameHeaderV1 protocol
unchanged.

Run:  python synth1080_lowent.py [fps] [WxH]
"""
import struct
import sys
import time

import numpy as np
import zmq

HEADER = struct.Struct("<4sHHQQIIIBBHI")  # FrameHeaderV1, 44 bytes


def build_base(w, h):
    eye = w // 2
    yy = np.linspace(0, 255, h, dtype=np.float32)[:, None]
    gray = np.repeat(yy, w, axis=1)
    gray[: h // 3] *= 0.55                       # darker sky
    xx = np.meshgrid(np.arange(w), np.arange(h))[0]
    for cx, cy, r, amp in [(eye * 0.3, h * 0.6, 90, 45), (eye * 0.7 + eye, h * 0.55, 130, 30),
                           (eye * 0.5, h * 0.8, 60, 60), (eye * 1.5, h * 0.75, 80, 50)]:
        d2 = (xx - cx) ** 2 + (np.arange(h)[:, None] - cy) ** 2
        gray += amp * np.exp(-d2 / (2 * r * r))
    g = np.clip(gray, 0, 255).astype(np.uint8)
    base = np.empty((h, w, 3), dtype=np.uint8)
    base[..., 0] = (g * 0.9).astype(np.uint8)    # B
    base[..., 1] = g                             # G
    base[..., 2] = (g * 0.8).astype(np.uint8)    # R
    return base


def main():
    fps = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    w, h = (int(x) for x in
            (sys.argv[2] if len(sys.argv) > 2 else "3840x1080").lower().split("x"))
    eye = w // 2
    base = build_base(w, h)
    hdr_tail = HEADER.size

    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.bind("tcp://127.0.0.1:15558")
    time.sleep(0.5)  # let the server's SUB connect before the first frame

    bw, bh = eye // 5, h // 5                     # bouncing patch
    px, py, vx, vy = eye / 4, h / 3, eye / 3.0, h / 4.0
    interval = 1.0 / fps
    next_t = time.monotonic()
    seq = 0
    while True:
        frame = base.copy()
        px += vx * interval
        py += vy * interval
        if not bw // 2 < px < eye - bw // 2:
            vx = -vx
            px += 2 * vx * interval
        if not bh // 2 < py < h - bh // 2:
            vy = -vy
            py += 2 * vy * interval
        x0, y0 = int(px - bw // 2), int(py - bh // 2)
        frame[y0:y0 + bh, x0:x0 + bw] = 235       # same patch, both eyes
        frame[y0:y0 + bh, eye + x0:eye + x0 + bw] = 235
        msg = HEADER.pack(
            b"ZED1", 1, hdr_tail, seq, int(time.time() * 1e9),
            w, h, w * 3, 3, 1, 0, w * h * 3,
        )
        pub.send(msg + frame.tobytes())
        seq += 1
        next_t += interval
        sleep = next_t - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)


if __name__ == "__main__":
    main()
