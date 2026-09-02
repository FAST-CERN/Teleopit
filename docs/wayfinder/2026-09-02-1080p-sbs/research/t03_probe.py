#!/usr/bin/env python3
"""t03 probe: segment the deployed NVENC path's E at 3840x1080 on REAL ZED
content, sweep bitrate tiers, and capture AU/SPS facts for the sbs-1080p map.

Subscribes to the live bridge IPC feed (FrameHeaderV1 + BGR8 SBS), raw-drives
the deployed _nvenc_child.py (system python3, pass_fds) exactly like the
t05 smoke, and times each stage of the wrapper's per-frame work:
  conv  = cv2.cvtColor BGR -> I420 into the preallocated (H*3/2, W) buffer
  write = framed F command over the pipe (6.2MB payload)
  enc   = wait for the lockstep A reply
Tier sweep 4M -> 8M -> 12M via PLAYING-state B commands (vbv follows).
Run on the Jetson in the teleimager env:  python t03_probe.py [W H]

Requires the bridge publishing at the probe's W/H, e.g.:
  zed_xr_bridge --endpoint ipc:///tmp/zed_xr_head.ipc --resolution HD1080 \
      --fps 30 --output-width 3840 --output-height 1080
"""
import os
import struct
import subprocess
import sys
import time

import numpy as np
import zmq

CHILD = "/home/unitree/teleimager/src/teleimager/_nvenc_child.py"
PY = "/usr/bin/python3"
IPC = "ipc:///tmp/zed_xr_head.ipc"
HDR = struct.Struct("<4sHHQQIIIBBHI")
sys.path.insert(0, os.path.dirname(CHILD))
import _nvenc_child as proto  # protocol layer only, no gi needed here

W = int(sys.argv[1]) if len(sys.argv) > 1 else 3840
H = int(sys.argv[2]) if len(sys.argv) > 2 else 1080
TIERS = [4_000_000, 8_000_000, 12_000_000]
WARMUP, MEASURE = 10, 90


def read_exact(fd, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            raise EOFError("au pipe closed")
        buf.extend(chunk)
    return bytes(buf)


def reply(rfd):
    cmd, n = proto._HDR.unpack(read_exact(rfd, proto._HDR.size))
    return cmd, (read_exact(rfd, n) if n else b"")


def send_cmd(fd, cmd, payload=b""):
    data = memoryview(payload).cast("B")
    hdr = memoryview(proto._HDR.pack(cmd, data.nbytes))
    for chunk in (hdr, data):
        while chunk:
            n = os.write(fd, chunk)
            chunk = chunk[n:]


def nal_types_and_level(au):
    """Annex-B scan -> (nal type list, sps level_idc or None)."""
    types, level, i = [], None, 0
    starts = []
    while i < len(au) - 3:
        if au[i:i + 4] == b"\x00\x00\x00\x01":
            starts.append(i + 4)
            i += 4
        elif au[i:i + 3] == b"\x00\x00\x01":
            starts.append(i + 3)
            i += 3
        else:
            i += 1
    for off in starts:
        if off < len(au):
            t = au[off] & 0x1F
            types.append(t)
            if t == 7 and off + 3 < len(au) and level is None:
                level = au[off + 3]  # profile_idc, constraints, level_idc
    return types, level


def stats(v):
    v = sorted(v)
    def pct(p):
        return v[min(int(len(v) * p), len(v) - 1)]
    return f"p10={pct(0.1)*1000:.1f}ms p50={pct(0.5)*1000:.1f}ms p95={pct(0.95)*1000:.1f}ms"


def main():
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.SUBSCRIBE, b"")
    sub.setsockopt(zmq.CONFLATE, 1)
    sub.setsockopt(zmq.RCVHWM, 1)
    sub.connect(IPC)
    time.sleep(0.5)

    rfd, wfd = os.pipe()
    proc = subprocess.Popen([PY, CHILD, str(wfd)], stdin=subprocess.PIPE,
                            stdout=None, stderr=None, bufsize=0,
                            pass_fds=(wfd,))
    os.close(wfd)

    import json
    import cv2
    yuv = np.empty((H * 3 // 2, W), dtype=np.uint8)

    cfg = {"width": W, "height": H, "fps": 30, "bitrate": TIERS[0],
           "iframeinterval": 30, "format": "I420"}
    send_cmd(proc.stdin.fileno(), b"C", json.dumps(cfg).encode())
    cmd, payload = reply(rfd)
    assert cmd == b"R", f"expected R got {cmd!r}"
    print(f"R: {json.loads(payload)}")

    sps_level = None
    for tier_i, bitrate in enumerate(TIERS):
        if tier_i:
            send_cmd(proc.stdin.fileno(), b"B", str(bitrate).encode())
            time.sleep(1.0)
        conv, write, enc, sizes = [], [], [], []
        n = 0
        while n < WARMUP + MEASURE:
            msg = sub.recv()
            hsz, w, h = (HDR.unpack_from(msg, 0)[i] for i in (2, 5, 6))
            assert (w, h) == (W, H), f"source is {w}x{h}, probe expects {W}x{H}"
            bgr = np.frombuffer(msg, dtype=np.uint8,
                                count=h * w * 3, offset=hsz).reshape(h, w, 3)
            t0 = time.perf_counter()
            cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420, dst=yuv)
            t1 = time.perf_counter()
            send_cmd(proc.stdin.fileno(), b"F", yuv)
            t2 = time.perf_counter()
            cmd, au = reply(rfd)
            t3 = time.perf_counter()
            assert cmd == b"A"
            n += 1
            if n > WARMUP:
                conv.append(t1 - t0)
                write.append(t2 - t1)
                enc.append(t3 - t2)
                sizes.append(len(au))
                if sps_level is None:
                    types, lvl = nal_types_and_level(au)
                    if lvl is not None:
                        sps_level = lvl
                        print(f"first AU NALs {types[:4]} SPS level_idc={sps_level} (50=5.0,51=5.1,52=5.2)")
        s = sorted(sizes)
        print(f"@{bitrate//1_000_000}M: conv[{stats(conv)}] write[{stats(write)}] "
              f"enc[{stats(enc)}] | E(conv+write+enc) "
              f"p50={1000*(sorted(c+w+e for c,w,e in zip(conv,write,enc))[len(conv)//2]):.1f}ms "
              f"| AU mean {sum(sizes)/len(sizes)/1024:.1f}KiB p10 {s[len(s)//10]/1024:.1f} "
              f"p90 {s[int(len(s)*0.9)]/1024:.1f} "
              f"(CBR nominal {bitrate/30/8/1024:.1f}KiB)")

    send_cmd(proc.stdin.fileno(), b"Q")
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    os.close(rfd)
    print("PROBE DONE")


if __name__ == "__main__":
    main()
