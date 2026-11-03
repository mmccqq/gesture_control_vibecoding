"""Sound effects from the macOS system sounds, played with afplay so no audio
library is needed."""

import shutil
import subprocess
import time
from pathlib import Path

SOUND_DIR = Path("/System/Library/Sounds")
EVENT_SOUNDS = {
    "start": "Submarine",
    "slice": "Pop",
    "combo": "Hero",
    "frost": "Glass",
    "thorn": "Basso",
    "miss": "Funk",
    "over": "Sosumi",
}


class Sounds:
    def __init__(self, enabled: bool = True, volume: float = 0.4):
        self.enabled = enabled and shutil.which("afplay") is not None
        self.volume = volume
        self._last: dict[str, float] = {}

    def play(self, event: str) -> None:
        name = EVENT_SOUNDS.get(event)
        if not self.enabled or name is None:
            return
        path = SOUND_DIR / f"{name}.aiff"
        now = time.monotonic()
        # Several slices in one frame should sound like one, not a stack.
        if not path.exists() or now - self._last.get(event, 0.0) < 0.06:
            return
        self._last[event] = now
        subprocess.Popen(["afplay", "-v", str(self.volume), str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
