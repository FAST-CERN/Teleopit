#!/usr/bin/env python3
"""t06 logcat stats parser (nvenc map e2e acceptance).

Parses Pico APK [HttpSignaling] stats lines from an `adb logcat -d` dump:
  ... I Unity : [HttpSignaling] stats: decodeFps=30.0 framesDecoded=4215
        avgJitterBuffer=50.9ms target=143703.2ms packetsLost=0 jitter=0.016s
Outputs: cumulative avgJB trace, instantaneous JB slope per inter-sample
window (delta target / delta frames -- the pacer-t03 "inst" method), decodeFps
distribution, loss totals. Usage:  python parse_stats.py <logcat.txt>
"""
import re
import sys

LINE = re.compile(
    r"\[HttpSignaling\] stats: decodeFps=([\d.]+) framesDecoded=(\d+) "
    r"avgJitterBuffer=([\d.]+)ms target=([\d.]+)ms packetsLost=(\d+) jitter=([\d.]+)s")


def main(path):
    rows = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        m = LINE.search(ln)
        if m:
            fps, dec, jb, tgt, lost, jit = m.groups()
            rows.append((float(fps), int(dec), float(jb), float(tgt),
                         int(lost), float(jit)))
    if not rows:
        print("no stats lines found")
        return 1
    print(f"samples={len(rows)} span_frames={rows[-1][1] - rows[0][1]} "
          f"decodeFps min/med/max={min(r[0] for r in rows)}/"
          f"{sorted(r[0] for r in rows)[len(rows)//2]}/{max(r[0] for r in rows)} "
          f"packetsLost_last={rows[-1][4]}")
    inst = []
    for a, b in zip(rows, rows[1:]):
        dd, dt = b[1] - a[1], b[3] - a[3]
        if dd > 0:
            inst.append(dt / dd)
    inst_s = sorted(inst)
    print(f"JB inst slope (delta target/delta frames): "
          f"p10={inst_s[int(len(inst_s)*0.1)]:.1f} "
          f"med={inst_s[len(inst_s)//2]:.1f} "
          f"p90={inst_s[int(len(inst_s)*0.9)]:.1f} ms")
    print("cum avgJB first->last: "
          f"{rows[0][2]:.1f} -> {rows[-1][2]:.1f} ms")
    print("trace (every ~5s): " + " ".join(f"{r[2]:.0f}" for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
