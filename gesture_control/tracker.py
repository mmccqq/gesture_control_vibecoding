"""Thin wrapper around MediaPipe's HandLandmarker (Tasks API)."""

from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "hand_landmarker.task"


class HandTracker:
    def __init__(self, model_path: Path = MODEL_PATH):
        if not model_path.exists():
            raise FileNotFoundError(
                f"Hand model not found at {model_path}. Run ./setup.sh to download it."
            )
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.6,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_ts = -1

    def detect(self, frame_bgr, timestamp_ms: int):
        """Return the 21 landmarks of the first detected hand, or None."""
        # VIDEO mode requires strictly increasing timestamps.
        timestamp_ms = max(timestamp_ms, self._last_ts + 1)
        self._last_ts = timestamp_ms
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        return result.hand_landmarks[0] if result.hand_landmarks else None

    def close(self) -> None:
        self._landmarker.close()
