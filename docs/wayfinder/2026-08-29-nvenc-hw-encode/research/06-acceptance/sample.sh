#!/usr/bin/env bash
# t06 round sampler (nvenc map e2e acceptance): CPU of the live
# teleimager-server (+ _nvenc_child when present) and per-interface tx bytes,
# every 2s, CSV to stdout. Run on the Jetson for the whole round window:
#   ./sample.sh <duration_s> > /tmp/nvenc_t06/samples_<tag>.csv
# CPU math (analysis side): d(utime+stime)/clk_tck / d(wall) * 100 = % of one core.
set -u
DUR="${1:-120}"
CLK_TCK=$(getconf CLK_TCK)

pids_cpu() {  # "pid utime+stime" for server and nvenc child if alive
  local srv ch
  srv=$(pgrep -f '[t]eleimager-server --config' | head -1)
  ch=$(pgrep -f 'nvenc_child.p[y] 3' | head -1)
  local out="-,-"
  if [ -n "$srv" ]; then
    out="$(awk '{print $14+$15}' /proc/$srv/stat 2>/dev/null)"
  fi
  out="$out,"
  if [ -n "$ch" ]; then
    out="$out$(awk '{print $14+$15}' /proc/$ch/stat 2>/dev/null)"
  else
    out="$out-"
  fi
  echo "$out"
}

t0=$(date +%s.%N)
# printf, NOT print: awk's default OFMT (%.6g) renders the epoch as 1.78832e+09
# and truncates it -- the loop then sees end in the past and exits instantly.
end=$(awk -v t="$t0" -v d="$DUR" 'BEGIN{printf "%.3f", t+d}')
while :; do
  now=$(date +%s.%N)
  awk -v n="$now" -v e="$end" 'BEGIN{exit !(n>=e)}' && break
  ts=$(date +%s.%N)
  cpu=$(pids_cpu)
  net=$(grep ':' /proc/net/dev | grep -v 'lo:' | awk '{sub(/:/,"",$1); print $1"tx="$10}' | tr '\n' ' ')
  echo "$ts,$cpu,$net"
  sleep 2
done
