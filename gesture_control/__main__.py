"""Run with:  python -m gesture_control [--no-preview] [--dry-run] [--camera N]"""

import argparse
import sys
import textwrap
import time

import cv2
import numpy as np
from mediapipe.tasks.python.vision import HandLandmarksConnections

from .config import Config
from .controller import Controller, Mode
from .gestures import extract_features
from .mac import Mac, accessibility_trusted, screen_size
from .settings import SETTINGS_PATH, Settings, SettingsError, SettingsWatcher
from .tracker import HandTracker

MODE_COLORS = {  # BGR
    Mode.IDLE: (128, 128, 128),
    Mode.MOVE: (80, 200, 80),
    Mode.SCROLL: (220, 160, 40),
    Mode.SWIPE: (40, 160, 240),
    Mode.FREEZE: (60, 60, 220),
    Mode.ACTION: (200, 80, 200),
}


def help_lines(settings: Settings) -> list[str]:
    """The current mappings, wrapped to fit the preview window."""
    items = [f"{k}:{v}" for k, v in settings.poses.items() if v != "none"]
    items += [f"{k}:{v}" for k, v in settings.gestures.items() if v != "none"]
    return textwrap.wrap("  ".join(items), 62) + ["[p] pause  [q] quit"]


def draw_overlay(frame, landmarks, shape: str, ctrl: Controller, cfg: Config, fps: float,
                 lines: list[str]) -> None:
    h, w = frame.shape[:2]
    l, t, r, b = cfg.active_box
    color = MODE_COLORS[ctrl.mode]
    cv2.rectangle(frame, (int(l * w), int(t * h)), (int(r * w), int(b * h)), color, 1)

    if landmarks:
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
        for c in HandLandmarksConnections.HAND_CONNECTIONS:
            cv2.line(frame, pts[c.start], pts[c.end], color, 2)
        for p in pts:
            cv2.circle(frame, p, 3, (255, 255, 255), -1)

    status = "PAUSED" if ctrl.paused else ctrl.mode.value.upper()
    if ctrl.left_down:
        status += " (button down)"
    if shape:
        status += f"   shape: {shape}"
    cv2.putText(frame, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    cv2.putText(frame, f"{fps:4.1f} fps  {ctrl.last_event}", (10, 56),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1)
    for i, line in enumerate(lines):
        cv2.putText(frame, line, (10, h - 12 - 20 * (len(lines) - 1 - i)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Control your Mac with hand gestures.")
    parser.add_argument("--camera", type=int, help="camera index (overrides settings)")
    parser.add_argument("--no-preview", action="store_true", help="don't show the camera window")
    parser.add_argument("--dry-run", action="store_true",
                        help="detect gestures but don't touch the mouse/keyboard")
    args = parser.parse_args()

    try:
        watcher = SettingsWatcher()
    except SettingsError as e:
        print(f"Invalid settings: {e}", file=sys.stderr)
        return 1
    cfg = watcher.settings.config
    if args.camera is not None:
        cfg.camera_index = args.camera
    print(f"Settings: {SETTINGS_PATH}")

    if not args.dry_run and not accessibility_trusted(prompt=True):
        print("Accessibility permission is required to control the mouse and keyboard.\n"
              "Enable it for the app running this script (Terminal, iTerm, VS Code...) in\n"
              "System Settings > Privacy & Security > Accessibility, then run again.\n"
              "(Use --dry-run to try gesture detection without it.)", file=sys.stderr)
        return 1

    cap = cv2.VideoCapture(cfg.camera_index, cv2.CAP_AVFOUNDATION)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.frame_height)
    if not cap.isOpened() or not cap.read()[0]:
        print("Could not read from the camera. Allow camera access for this app in\n"
              "System Settings > Privacy & Security > Camera, or try --camera 1.",
              file=sys.stderr)
        return 1

    tracker = HandTracker()
    ctrl = Controller(watcher.settings, Mac(dry_run=args.dry_run), *screen_size())
    lines = help_lines(watcher.settings)
    fps, last_t = 0.0, time.monotonic()
    last_poll = last_t
    print("Gesture control running. " + ("Press q in the preview window to quit."
                                         if not args.no_preview else "Ctrl+C to quit."))
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)  # mirror, so moving right moves right
            now = time.monotonic()
            landmarks = tracker.detect(frame, int(now * 1000))
            h, w = frame.shape[:2]
            features = (extract_features(landmarks, w / h, ctrl.cfg)
                        if landmarks else None)
            ctrl.update(features, now)

            if now - last_poll > 1.0:
                last_poll = now
                if new := watcher.poll():
                    ctrl.apply_settings(new)
                    lines = help_lines(new)

            fps = 0.9 * fps + 0.1 / max(now - last_t, 1e-6)
            last_t = now
            if args.no_preview:
                continue
            shape = features.pose.value if features else ""
            canvas = frame if ctrl.cfg.preview_camera_image else np.zeros_like(frame)
            draw_overlay(canvas, landmarks, shape, ctrl, ctrl.cfg, fps, lines)
            cv2.imshow("Gesture Control", canvas)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("p"):
                ctrl.paused = not ctrl.paused
    except KeyboardInterrupt:
        pass
    finally:
        ctrl.close()
        tracker.close()
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
