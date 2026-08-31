#!/usr/bin/env python3
"""nvenc_child.py — t02 原型：NVENC 编码子进程（系统 /usr/bin/python3 + gi，无 numpy）。

管线（t01 已验证参数）：appsrc(BGRx) ! nvvidconv ! NVMM NV12 ! nvv4l2h264enc(CBR)
! appsink。gst 1.16 gi 坑（t01 §5）：pull-sample / push-buffer 必须走 emit signal。

Lockstep 假设：零延迟无 B 帧，一帧进恰好一个 AU 出（t01_roundtrip 60 帧实证）。
若实际出现 0/2 AU，父进程会看到流错位 —— 记入 03 票问题清单。

stderr 直通父控制台（NVMEDIA 会话建立打印 = 首帧/重启恢复常数的观测面）。
"""
import json
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proto_ipc

import gi
gi.require_version("Gst", "1.0")
from gi.repository import GObject, Gst  # noqa: E402

# force-IDR 以 action signal 形式存在（JP 5.1.1 gst-inspect 实证），探测候选名
FORCE_IDR_CANDIDATES = ("force-IDR", "forceIDR", "force-idr")


def build_pipeline(w, h, fps, bitrate, fmt="BGRx"):
    return (
        f"appsrc name=src is-live=true block=true do-timestamp=false "
        f"caps=video/x-raw,format={fmt},width={w},height={h},framerate={fps}/1 "
        "! nvvidconv ! video/x-raw(memory:NVMM),format=NV12 "
        f"! nvv4l2h264enc name=enc control-rate=1 bitrate={bitrate} "
        "insert-sps-pps=true maxperf-enable=true "
        "! appsink name=sink sync=false max-buffers=1 drop=true"
    )


def main():
    out = sys.stdout.buffer
    cmd, payload = proto_ipc.recv(sys.stdin.buffer)
    if cmd != b"C":
        proto_ipc.send(out, b"L", f"expected C config, got {cmd!r}".encode())
        return 1
    cfg = json.loads(payload)
    w, h, fps, bitrate = cfg["width"], cfg["height"], cfg["fps"], cfg["bitrate"]
    fmt = cfg.get("format", "BGRx")  # I420 传输实验：2.76MB vs 7.37MB

    Gst.init(None)
    pipeline = Gst.parse_launch(build_pipeline(w, h, fps, bitrate, fmt))
    src = pipeline.get_by_name("src")
    enc = pipeline.get_by_name("enc")
    sink = pipeline.get_by_name("sink")

    # force-IDR 探测：JP 5.1.1 上它是 action signal（gst-inspect 末行
    # `"force-IDR" : void user_function(GstElement*)`），不是属性——set_property 必败。
    # 注意：探测绝不能真 emit——NULL 态 emit 会触发 C 层 printf 直接写 fd 1
    # （"device is not open\nError while signalling force IDR"），裸字节污染协议流。
    force_signal = None
    for name in FORCE_IDR_CANDIDATES:
        if GObject.signal_lookup(name, type(enc)) != 0:
            force_signal = name
            proto_ipc.send(out, b"L", f"force-IDR signal found: {name!r}".encode())
            break
    if force_signal is None:
        proto_ipc.send(out, b"L", b"force-IDR signal NOT found on this encoder")

    pipeline.set_state(Gst.State.PLAYING)
    proto_ipc.send(out, b"R", json.dumps({"force_idr_prop": force_signal, "w": w, "h": h}).encode())

    i = 0
    while True:
        signal.alarm(60)  # 停滞自杀：父进程以 EOF 感知并走重启路径
        try:
            cmd, payload = proto_ipc.recv(sys.stdin.buffer)
        except EOFError:
            break
        if cmd == b"F":
            buf = Gst.Buffer.new_wrapped(payload)
            buf.pts = i * Gst.SECOND // fps
            buf.duration = Gst.SECOND // fps
            src.emit("push-buffer", buf)  # gi 1.16: signal 形式
            sample = sink.emit("pull-sample")
            if sample is None:
                proto_ipc.send(out, b"L", b"pull-sample None (stall/EOS) -> child exit")
                break
            data = sample.get_buffer().extract_dup(0, sample.get_buffer().get_size())
            proto_ipc.send(out, b"A", data)
            i += 1
        elif cmd == b"B":
            enc.set_property("bitrate", int(payload))
            proto_ipc.send(out, b"L", f"bitrate set: {int(payload)}".encode())
        elif cmd == b"I":
            if force_signal:
                enc.emit(force_signal)  # action signal: 下一帧变 IDR
                proto_ipc.send(out, b"L", b"force-IDR emitted for next frame")
            else:
                proto_ipc.send(out, b"L", b"force-IDR unavailable: I ignored")
        elif cmd == b"Q":
            break

    signal.alarm(0)
    pipeline.set_state(Gst.State.NULL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
