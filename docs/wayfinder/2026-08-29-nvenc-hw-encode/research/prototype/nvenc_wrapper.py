"""nvenc_wrapper.py — t02 原型：teleimager 侧 wrapper（跑在 teleimager/xr_tele env）。

照 `jetson_software_encode_frame` 先例的形状（image_server.py:135）：喂 BGR ndarray、
收 Annex-B AU、`last_encode_s` 供 pacer 预算；外加 REMB 语义的两根控制线（码率/force-IDR）。
t04 合入时此逻辑改写为 `h264.H264Encoder._encode_frame` 的替换体，原型只验通路。

崩溃语义雏形：AU 读 EOF/超时 -> 硬杀重启 -> 同帧重发（新会话首帧天然 IDR +
insert-sps-pps）-> 上层无帧丢失。重启计数与 gap 计时留观测。
"""
import os
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proto_ipc


class ChildDied(Exception):
    pass


def nal_types(au: bytes):
    """Annex-B AU 的 NAL 类型列表（5=IDR 7=SPS 8=PPS）。"""
    types = []
    i = 0
    n = len(au)
    while i + 4 < n:
        if au[i] == 0 and au[i + 1] == 0 and au[i + 2] == 1:
            start = 3
        elif au[i] == 0 and au[i + 1] == 0 and au[i + 2] == 0 and au[i + 3] == 1:
            start = 4
        else:
            i += 1
            continue
        if i + start < n:
            types.append(au[i + start] & 0x1F)
        i += start
    return types


def _percentile(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    idx = min(int(len(sorted_vals) * p), len(sorted_vals) - 1)
    return sorted_vals[idx]


def fmt_stats(ms_list):
    v = sorted(x * 1000.0 for x in ms_list)
    if not v:
        return "n=0"
    return (f"n={len(v)} min={v[0]:.2f} p50={_percentile(v, 0.5):.2f} "
            f"p95={_percentile(v, 0.95):.2f} max={v[-1]:.2f} mean={sum(v)/len(v):.2f} ms")


class NvencSubprocessEncoder:
    def __init__(self, width, height, fps=30, bitrate=4_000_000,
                 child_argv=None, au_timeout=2.0, verbose=True, format="BGRx"):
        self.width, self.height, self.fps = width, height, fps
        self.bitrate = bitrate
        self.format = format
        here = os.path.dirname(os.path.abspath(__file__))
        self.child_argv = child_argv or ["/usr/bin/python3", os.path.join(here, "nvenc_child.py")]
        self.au_timeout = au_timeout
        self.verbose = verbose
        self.force_idr_prop = None      # 子进程 R 消息回报
        self.last_encode_s = 0.0        # pacer 预算兼容（jetson_software_encode_frame 同名属性）
        self.last_restart_gap_s = None  # 最近一次 重启->同帧AU 恢复时长
        self._restart_t0 = None
        self.proc = None
        # 观测累计
        self.stats = {"conv_s": [], "write_s": [], "wait_s": [], "encode_s": [],
                      "restarts": 0, "stalls": 0, "au_bytes": 0, "frames": 0}
        # BGRx 复用缓冲：alpha 面一次性铺 255
        self._bgrx = np.full((height, width, 4), 255, dtype=np.uint8)
        try:
            import cv2
            if format == "I420":
                # 传输实验：I420 平面 2.76MB（管道字节 -62%），nvvidconv 白名单内
                self._yuv = np.empty((height * 3 // 2, width), dtype=np.uint8)
                self._cvt = lambda bgr: cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420, dst=self._yuv)
            else:
                self._cvt = lambda bgr: cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA, dst=self._bgrx)
        except ImportError:
            self._cvt = None  # numpy 兜底（慢路径，代价进 conv 统计）

    # ---- 生命周期 ----

    def start(self):
        self._spawn()

    def _spawn(self):
        t0 = time.perf_counter()
        self.proc = subprocess.Popen(
            self.child_argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=None, bufsize=0, cwd=os.path.dirname(self.child_argv[-1]),
        )
        try:
            proto_ipc.send_fd(self.proc.stdin.fileno(), b"C",
                              (f'{{"width":{self.width},"height":{self.height},'
                               f'"fps":{self.fps},"bitrate":{self.bitrate},'
                               f'"format":"{self.format}"}}').encode())
            while True:
                cmd, payload = proto_ipc.recv_msg_fd(self.proc.stdout.fileno(), 10.0)
                if cmd == b"L":
                    if self.verbose:
                        print(f"[child] {payload.decode(errors='replace')}")
                    continue
                if cmd != b"R":
                    raise ChildDied(f"expected R, got {cmd!r}")
                import json
                self.force_idr_prop = json.loads(payload).get("force_idr_prop")
                break
        except Exception:
            self.proc.kill()  # 握手失败不留孤儿（NVENC 占用）
            raise
        self.spawn_s = time.perf_counter() - t0  # spawn->R 就绪（不含 NVMEDIA 首帧建立）

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                proto_ipc.send_fd(self.proc.stdin.fileno(), b"Q")
            except OSError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.proc:
            for s in (self.proc.stdin, self.proc.stdout):
                try:
                    s.close()
                except OSError:
                    pass

    def _hard_restart(self, reason):
        self.stats["restarts"] += 1
        if self.proc:
            self.proc.kill()
            self.proc.wait()
            for s in (self.proc.stdin, self.proc.stdout):
                try:
                    s.close()
                except OSError:
                    pass
        print(f"[wrapper] child restart #{self.stats['restarts']}: {reason}")
        self._spawn()

    # ---- 控制线 ----

    def set_bitrate(self, v):
        self.bitrate = int(v)
        if self.proc and self.proc.poll() is None:
            proto_ipc.send_fd(self.proc.stdin.fileno(), b"B", str(int(v)).encode())

    # ---- 主路径 ----

    def encode(self, bgr: np.ndarray, force_keyframe: bool = False) -> bytes:
        """BGR(H,W,3) -> Annex-B AU。崩溃/停滞自动重启并同帧重试一次。"""
        for attempt in (1, 2):
            try:
                au = self._encode_once(bgr, force_keyframe or attempt == 2)
                if attempt == 2 and self._restart_t0 is not None:
                    # 重启->同帧 AU 返回的恢复时长（crash 测试的观测口径之一）
                    self.last_restart_gap_s = time.perf_counter() - self._restart_t0
                    self._restart_t0 = None
                return au
            except (ChildDied, TimeoutError, OSError) as e:
                if attempt == 2:
                    raise
                self._restart_t0 = time.perf_counter()
                self._hard_restart(f"{type(e).__name__}: {e}")

    def _encode_once(self, bgr, force_keyframe):
        t0 = time.perf_counter()
        if self.proc.poll() is not None:
            raise ChildDied("child exited before encode")
        # BGR -> 传输格式（t01 §3：24 位 BGR 被 nvvidconv 拒；BGRx 或 I420）
        if self._cvt is not None:
            self._cvt(bgr)
        else:
            np.copyto(self._bgrx[..., :3], bgr)
        payload = self._yuv if self.format == "I420" and self._cvt is not None else self._bgrx
        t1 = time.perf_counter()
        if force_keyframe:
            if self.force_idr_prop:
                proto_ipc.send_fd(self.proc.stdin.fileno(), b"I")
            elif self.verbose:
                print("[wrapper] force_keyframe requested but child has no force-IDR")
        # ndarray 缓冲直接进 os.write，省一次 tobytes 整帧拷贝
        proto_ipc.send_fd(self.proc.stdin.fileno(), b"F", payload)
        t2 = time.perf_counter()
        out_fd = self.proc.stdout.fileno()
        while True:
            cmd, au = proto_ipc.recv_msg_fd(out_fd, self.au_timeout)
            if cmd == b"A":
                break
            if cmd == b"L":
                if self.verbose:
                    print(f"[child] {au.decode(errors='replace')}")
                continue
            raise ChildDied(f"unexpected child msg {cmd!r}")
        t3 = time.perf_counter()
        self.last_encode_s = t3 - t0
        st = self.stats
        st["conv_s"].append(t1 - t0); st["write_s"].append(t2 - t1); st["wait_s"].append(t3 - t2)
        st["encode_s"].append(self.last_encode_s)
        st["au_bytes"] += len(au); st["frames"] += 1
        return au
