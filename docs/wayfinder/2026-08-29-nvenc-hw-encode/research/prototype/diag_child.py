#!/usr/bin/env python3
"""diag_child.py — 子进程握手单独诊断：发 C、限时收消息、报告子进程死活。"""
import os
import select
import struct
import subprocess
import sys
import time

cfg = b'{"width":2560,"height":720,"fps":30,"bitrate":4000000}'
p = subprocess.Popen(["/usr/bin/python3", "/tmp/nvenc_t02/nvenc_child.py"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                     bufsize=0, cwd="/tmp/nvenc_t02")
p.stdin.write(struct.pack("<cI", b"C", len(cfg)) + cfg)
p.stdin.flush()
fd = p.stdout.fileno()
deadline = time.time() + 20.0
t0 = time.time()
while time.time() < deadline:
    r, _, _ = select.select([fd], [], [], 1.0)
    if not r:
        print(f"[wait] t+{time.time()-t0:.0f}s no msg, child poll={p.poll()}", flush=True)
        continue
    hdr = os.read(fd, 5)
    if not hdr:
        print(f"[eof] t+{time.time()-t0:.1f}s child stdout closed, rc={p.poll()}", flush=True)
        break
    cmd, n = struct.unpack("<cI", hdr)
    pl = os.read(fd, n) if n else b""
    print(f"[msg] t+{time.time()-t0:.2f}s {cmd!r} {pl[:120]!r}", flush=True)
    if cmd == b"R":
        print("CHILD_OK", flush=True)
        break
p.kill()
p.wait()
print("diag done", flush=True)
