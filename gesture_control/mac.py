"""macOS mouse/keyboard output via Quartz CGEvents."""

import math
import subprocess
import time

import Quartz as Q  # must be imported before AppKit so NSEvent.CGEvent() bridges
from AppKit import NSEvent, NSEventTypeSystemDefined
from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

# Virtual keycodes (US ANSI layout).
KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
    "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "return": 36,
    "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45,
    "m": 46, ".": 47, "tab": 48, "space": 49, "`": 50, "delete": 51, "escape": 53,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111, "home": 115, "pageup": 116,
    "forwarddelete": 117, "end": 119, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126,
}
ARROW_KEYS = {123, 124, 125, 126}
MODIFIERS = {
    "cmd": Q.kCGEventFlagMaskCommand,
    "shift": Q.kCGEventFlagMaskShift,
    "ctrl": Q.kCGEventFlagMaskControl,
    "alt": Q.kCGEventFlagMaskAlternate,
    "fn": Q.kCGEventFlagMaskSecondaryFn,
}
# Real arrow-key presses carry these flags; Mission Control shortcuts can
# ignore synthetic arrows without them.
ARROW_FLAGS = Q.kCGEventFlagMaskSecondaryFn | Q.kCGEventFlagMaskNumericPad

# NX_KEYTYPE_* codes for media keys (sent as system-defined events).
MEDIA_KEYS = {
    "volume_up": 0, "volume_down": 1, "mute": 7,
    "play_pause": 16, "next_track": 17, "previous_track": 18,
}


def accessibility_trusted(prompt: bool = True) -> bool:
    """True if this process may control the mouse/keyboard. With prompt=True,
    macOS shows the 'allow in Accessibility settings' dialog if it isn't."""
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))


def screen_size() -> tuple[float, float]:
    b = Q.CGDisplayBounds(Q.CGMainDisplayID())
    return b.size.width, b.size.height


class Mac:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._last_up_t = 0.0
        self._last_up_pos = (-1e9, -1e9)
        self._click_count = 0
        self._double_click_s = NSEvent.doubleClickInterval()

    def _post(self, event) -> None:
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def _mouse(self, kind, x: float, y: float, button, click_count: int = 0) -> None:
        if self.dry_run:
            return
        ev = Q.CGEventCreateMouseEvent(None, kind, (x, y), button)
        if click_count:
            Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventClickState, click_count)
        self._post(ev)

    def move(self, x: float, y: float) -> None:
        self._mouse(Q.kCGEventMouseMoved, x, y, Q.kCGMouseButtonLeft)

    def left_down(self, x: float, y: float) -> None:
        # Consecutive clicks close in time and space become double/triple clicks.
        near = math.hypot(x - self._last_up_pos[0], y - self._last_up_pos[1]) < 10
        if near and time.monotonic() - self._last_up_t < self._double_click_s:
            self._click_count += 1
        else:
            self._click_count = 1
        if self.dry_run:
            print(f"[dry-run] left down x{self._click_count}")
        self._mouse(Q.kCGEventLeftMouseDown, x, y, Q.kCGMouseButtonLeft, self._click_count)

    def left_drag(self, x: float, y: float) -> None:
        self._mouse(Q.kCGEventLeftMouseDragged, x, y, Q.kCGMouseButtonLeft, self._click_count)

    def left_up(self, x: float, y: float) -> None:
        if self.dry_run:
            print("[dry-run] left up")
        self._mouse(Q.kCGEventLeftMouseUp, x, y, Q.kCGMouseButtonLeft, self._click_count)
        self._last_up_t = time.monotonic()
        self._last_up_pos = (x, y)

    def click(self, x: float, y: float) -> None:
        self.left_down(x, y)
        self.left_up(x, y)

    def double_click(self, x: float, y: float) -> None:
        if self.dry_run:
            print("[dry-run] double click")
            return
        for n in (1, 2):
            self._mouse(Q.kCGEventLeftMouseDown, x, y, Q.kCGMouseButtonLeft, n)
            self._mouse(Q.kCGEventLeftMouseUp, x, y, Q.kCGMouseButtonLeft, n)

    def right_click(self, x: float, y: float) -> None:
        if self.dry_run:
            print("[dry-run] right click")
        self._mouse(Q.kCGEventRightMouseDown, x, y, Q.kCGMouseButtonRight, 1)
        self._mouse(Q.kCGEventRightMouseUp, x, y, Q.kCGMouseButtonRight, 1)

    def scroll(self, dy_px: int) -> None:
        if self.dry_run or dy_px == 0:
            return
        ev = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitPixel, 1, dy_px)
        self._post(ev)

    def key(self, keycode: int, flags: int = 0) -> None:
        if keycode in ARROW_KEYS:
            flags |= ARROW_FLAGS
        if self.dry_run:
            print(f"[dry-run] key {keycode} flags {flags:#x}")
            return
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, keycode, down)
            Q.CGEventSetFlags(ev, flags)
            self._post(ev)

    def media_key(self, key_type: int) -> None:
        if self.dry_run:
            print(f"[dry-run] media key {key_type}")
            return
        for state in (0xA, 0xB):  # key down, key up
            ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                NSEventTypeSystemDefined, (0, 0), state << 8, 0, 0, None, 8,
                (key_type << 16) | (state << 8), -1)
            self._post(ev.CGEvent())

    def open_app(self, name: str) -> None:
        if self.dry_run:
            print(f"[dry-run] open {name}")
            return
        subprocess.Popen(["open", "-a", name],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
