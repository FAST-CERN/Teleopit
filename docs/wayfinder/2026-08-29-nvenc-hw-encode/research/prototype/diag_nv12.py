#!/usr/bin/env python3
"""diag_nv12.py — NV12 直传可行性裁决（Jetson）。

cv2 无 COLOR_BGR2YUV_NV12（仅解码方向）→ 唯一 CPU 侧组合 =
BGR->I420 (cv2) + UV 平面交织成 NV12 (numpy strided scatter)。
测该组合耗时 vs 纯 I420，判定是否值得换 NV12 caps 去省 VIC 的 UV 交织。
"""
import time

import cv2
import numpy as np

W, H = 2560, 720
src = np.random.randint(0, 255, (H, W, 3), np.uint8)
i420 = np.empty((H * 3 // 2, W), np.uint8)
nv12 = np.empty((H * 3 // 2, W), np.uint8)
nv12[:H] = i420[:H]  # Y 面共享同一缓冲（交织只动下半）


def to_nv12(bgr):
    cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420, dst=i420)
    nv12[:H] = i420[:H]
    quart = H // 4  # I420 扁平缓冲里 U/V 各占 H/4 行（W 宽），交织目标半高 W/2 宽
    nv12[H:, 0::2] = i420[H:H + quart].reshape(H // 2, W // 2)     # U -> 偶列
    nv12[H:, 1::2] = i420[H + quart:].reshape(H // 2, W // 2)      # V -> 奇列


def bench(fn, n=50):
    t = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn(src)
        t.append(time.perf_counter() - t0)
    t.sort()
    return t[len(t) // 2] * 1000


print(f"conv I420 only:        p50 {bench(lambda s: cv2.cvtColor(s, cv2.COLOR_BGR2YUV_I420, dst=i420)):.2f} ms")
print(f"conv I420+UV interleave: p50 {bench(to_nv12):.2f} ms")
print("DONE")
