from __future__ import annotations

import os
import select
import sys
from dataclasses import dataclass

_IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class TerminalKeyEvent:
    key: str


class TerminalKeyboardReader:
    """Non-blocking console keyboard reader.

    POSIX: termios cbreak on stdin. Windows: msvcrt.kbhit/getwch on the
    console — same event surface (single-char keys; Esc arrives as '\\x1b',
    Ctrl-C as '\\x03', arrow keys as a two-event escape pair which callers
    ignore). Degrades to inactive when stdin is not a tty / no console is
    attached (pipes, services, CI).
    """

    def __init__(self) -> None:
        self._fd: int | None = None
        self._old_attrs: list[object] | None = None
        if not sys.stdin.isatty():
            return
        if _IS_WINDOWS:
            try:
                import msvcrt  # noqa: F401  (availability probe)
            except ImportError:
                self.close()
                return
            # Represent the Windows backend with a sentinel fd so `active`
            # and the close() contract stay uniform across platforms.
            self._fd = -1
            self._old_attrs = []
            return
        try:
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._old_attrs = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        except Exception:
            self.close()

    @property
    def active(self) -> bool:
        if _IS_WINDOWS:
            return self._fd == -1 and self._old_attrs is not None
        return self._fd is not None and self._old_attrs is not None

    def poll(self) -> tuple[TerminalKeyEvent, ...]:
        if _IS_WINDOWS:
            return self._poll_windows()
        return self._poll_posix()

    def _poll_posix(self) -> tuple[TerminalKeyEvent, ...]:
        if not self.active or self._fd is None:
            return ()
        ready, _, _ = select.select([self._fd], [], [], 0.0)
        if not ready:
            return ()

        events: list[TerminalKeyEvent] = []
        while True:
            try:
                chars = os.read(self._fd, 32)
            except BlockingIOError:
                break
            if not chars:
                break
            for char in chars.decode("utf-8", errors="ignore"):
                if char:
                    events.append(TerminalKeyEvent(key=char))
            ready, _, _ = select.select([self._fd], [], [], 0.0)
            if not ready:
                break
        return tuple(events)

    def _poll_windows(self) -> tuple[TerminalKeyEvent, ...]:
        if not self.active:
            return ()
        import msvcrt

        events: list[TerminalKeyEvent] = []
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                # Arrow/function keys: consume the discriminator code and
                # emit a two-event escape pair (ignored by current callers).
                if msvcrt.kbhit():
                    msvcrt.getwch()
                events.append(TerminalKeyEvent(key="\x1b"))
                continue
            if ch:
                events.append(TerminalKeyEvent(key=ch))
        return tuple(events)

    def close(self) -> None:
        if _IS_WINDOWS:
            self._fd = None
            self._old_attrs = None
            return
        if self._fd is None or self._old_attrs is None:
            self._fd = None
            self._old_attrs = None
            return
        try:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_attrs)
        finally:
            self._fd = None
            self._old_attrs = None
