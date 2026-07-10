"""
Input abstraction layer.

KeyboardInput is a stand-in for the real hardware: rotary encoder rotation
becomes NEXT/PREV, the encoder's push-button becomes SELECT, and a second
physical button (for skipping tracks) becomes SKIP.

When the GPIO hardware arrives, write a GpioInput class with the same
wait_for_event()/poll_event() interface (fed by encoder interrupt callbacks
pushing onto a queue), and nothing in menu.py has to change.
"""
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

    def _read_key(self):
        old_settings = termios.tcgetattr(self._fd)
        try:
            tty.setraw(self._fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":  # start of an arrow-key escape sequence
                ch += sys.stdin.read(2)
        finally:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, old_settings)
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
