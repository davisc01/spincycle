"""
Input abstraction layer.

KeyboardInput is a stand-in for the real hardware: rotary encoder rotation
becomes NEXT/PREV, the encoder's push-button becomes SELECT, and a second
physical button (for skipping tracks) becomes SKIP.

When the GPIO hardware arrives, write a GpioInput class with the same
wait_for_event()/poll_event() interface (fed by encoder interrupt callbacks
pushing onto a queue), and nothing in menu.py has to change.
"""
import atexit
import select
import sys
import termios
import tty


class Event:
    NEXT = "NEXT"      # rotate one direction
    PREV = "PREV"      # rotate the other direction
    SELECT = "SELECT"  # encoder push-button
    SKIP = "SKIP"       # dedicated skip button
    QUIT = "QUIT"


class KeyboardInput:
    """
    w / Up-arrow   -> NEXT
    s / Down-arrow -> PREV
    Enter / Space  -> SELECT
    k              -> SKIP
    q              -> QUIT
    """

    def __init__(self):
        self._fd = sys.stdin.fileno()
        self._old_settings = termios.tcgetattr(self._fd)
        # cbreak (not raw) so Ctrl-C still raises SIGINT as a force-quit
        # escape hatch. Set once for the process lifetime rather than
        # toggling per-keystroke: select() on a canonical-mode fd only
        # reports readiness after a full line (i.e. Enter) is buffered by
        # the kernel, so poll_event()'s select() would never see a lone
        # 'k'/'q' press while the tty was left in cooked mode between reads.
        tty.setcbreak(self._fd)
        atexit.register(self.close)

    def close(self):
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)

    def _read_key(self):
        ch = sys.stdin.read(1)
        if ch == "\x1b":  # start of an arrow-key escape sequence
            ch += sys.stdin.read(2)
        return ch

    def _key_to_event(self, key):
        if key in ("w", "W", "\x1b[A"):
            return Event.NEXT
        if key in ("s", "S", "\x1b[B"):
            return Event.PREV
        if key in ("\r", "\n", " "):
            return Event.SELECT
        if key in ("k", "K"):
            return Event.SKIP
        if key in ("q", "Q"):
            return Event.QUIT
        return None

    def wait_for_event(self):
        """Blocking read of the next event."""
        while True:
            key = self._read_key()
            event = self._key_to_event(key)
            if event is not None:
                return event

    def poll_event(self, timeout=0.1):
        """Non-blocking check, used while a video plays in the background."""
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            return self.wait_for_event()
        return None
