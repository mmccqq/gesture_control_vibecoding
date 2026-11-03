"""Reads the camera and runs hand tracking on a background thread, so hand
detection overlaps with drawing the window instead of taking turns with it.
(Done one after the other, the two take a little over one camera frame, so
every other frame was missed and the game ran at 15 fps.)"""

import threading
import time

import cv2

from gesture_control.tracker import HandTracker


class TrackedCamera:
    def __init__(self, index: int, width: int = 640, height: int = 480):
        self._cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.ok = self._cap.isOpened() and self._cap.read()[0]
        self._tracker = HandTracker() if self.ok else None
        self._cond = threading.Condition()
        self._latest = None  # (frame, landmarks, timestamp)
        self._seq = 0
        self._running = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._running = True
        self._thread.start()

    def _run(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)  # mirror, so moving right moves right
            now = time.monotonic()
            landmarks = self._tracker.detect(frame, int(now * 1000))
            with self._cond:
                self._latest = (frame, landmarks, now)
                self._seq += 1
                self._cond.notify_all()

    def next(self, last_seq: int, timeout: float = 0.1):
        """Wait for a frame newer than `last_seq`. Returns (seq, frame, landmarks,
        timestamp), or None if none arrived within `timeout`."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._seq != last_seq, timeout):
                return None
            return (self._seq, *self._latest)

    def close(self) -> None:
        self._running = False
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._tracker:
            self._tracker.close()
        self._cap.release()
