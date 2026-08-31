"""proto_ipc.py — t02 原型父子进程消息帧定（stdlib only，两侧共用）。

协议：5 字节头 `cmd(1 ASCII) + payload_len(uint32 LE)` + payload。
父(teleimager env) -> 子(系统 python3 + gi)：
  C 配置 JSON {width,height,fps,bitrate}（首条）；F 一帧 BGRx；B 码率(ASCII int)；
  I force-IDR（作用于下一帧）；Q 退出。
子 -> 父：R 就绪 JSON {force_idr_prop}；A 一个 Annex-B AU；L 日志行（父读 A 时跳过收集）。

两侧 IO 路径不同：子走 buffered file obj（单线程 lockstep，flush 即可）；
父走裸 fd + select（需要超时判定子进程死亡/停滞）。
"""
import select
import struct

_HDR = struct.Struct("<cI")
HDR_SIZE = _HDR.size  # 5


def frame_msg(cmd: bytes, payload: bytes = b"") -> bytes:
    assert len(cmd) == 1
    return _HDR.pack(cmd, len(payload)) + payload


# ---- 子进程侧（buffered file obj，阻塞 read 恰好 n 字节或 EOF） ----

def send(stream, cmd: bytes, payload: bytes = b"") -> None:
    stream.write(frame_msg(cmd, payload))
    stream.flush()


def recv(stream):
    """return (cmd, payload)；EOF -> EOFError。"""
    hdr = stream.read(HDR_SIZE)
    if not hdr:
        raise EOFError
    if len(hdr) != HDR_SIZE:
        raise EOFError(f"short header {len(hdr)}")
    cmd, n = _HDR.unpack(hdr)
    payload = stream.read(n) if n else b""
    if n and len(payload) != n:
        raise EOFError(f"short payload {len(payload)}/{n}")
    return cmd, payload


# ---- 父进程侧（裸 fd + select 超时） ----

def send_fd(fd: int, cmd: bytes, payload = b"") -> None:
    """头与负载分两次写，避免 7.37MB 帧的整帧拼接拷贝；payload 可为 buffer 协议对象。"""
    import os
    mv = memoryview(payload).cast("B")
    hdr = _HDR.pack(cmd, mv.nbytes)
    for chunk in (memoryview(hdr), mv):
        while chunk:
            written = os.write(fd, chunk)
            chunk = chunk[written:]


def recv_exact_fd(fd: int, n: int, timeout: float):
    """读满 n 字节；EOF -> EOFError；超时 -> TimeoutError。"""
    import os

    buf = bytearray()
    while len(buf) < n:
        remaining = timeout - 0  # per-call timeout budget for this read
        r, _, _ = select.select([fd], [], [], remaining)
        if not r:
            raise TimeoutError(f"fd {fd} read timeout after {timeout}s")
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            raise EOFError("child stdout closed")
        buf.extend(chunk)
    return bytes(buf)


def recv_msg_fd(fd: int, timeout: float):
    """一条完整消息；EOF/超时语义同 recv_exact_fd。"""
    hdr = recv_exact_fd(fd, HDR_SIZE, timeout)
    cmd, n = _HDR.unpack(hdr)
    if n:
        # payload 跟头同批到达是常态；超时预算整体共用（头已到手，payload 不会再等）
        payload = recv_exact_fd(fd, n, timeout)
    else:
        payload = b""
    return cmd, payload
