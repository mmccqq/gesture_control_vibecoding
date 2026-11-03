"""Run from the project root with:  .venv/bin/python -m fruit_slice [--camera N] [--mute] [--no-log]"""

import argparse
import sys
import time
from pathlib import Path

import cv2

from gesture_control.gestures import Pose

from . import render
from .camera import TrackedCamera
from .game import Game, GameConfig, State
from .hand import HandInput
from .log import GameLog
from .sound import Sounds

WINDOW = "Orchard Blade"
BEST_PATH = Path(__file__).resolve().parent / "best_score.txt"


def load_best() -> int:
    try:
        return int(BEST_PATH.read_text().strip())
    except (OSError, ValueError):
        return 0


def save_best(score: int) -> None:
    try:
        BEST_PATH.write_text(f"{score}\n")
    except OSError as e:
        print(f"Could not save best score: {e}", file=sys.stderr)


def handle_hold(game: Game, pose: Pose | None) -> None:
    """Thumbs up starts / resumes; holding a fist pauses."""
    if pose is Pose.THUMBS_UP and game.state in (State.MENU, State.OVER):
        game.start()
    elif pose is Pose.THUMBS_UP and game.state is State.PAUSED:
        game.toggle_pause()
    elif pose is Pose.FIST and game.state is State.PLAYING:
        game.toggle_pause()


def handle_key(game: Game, key: int, fullscreen: bool) -> bool | None:
    """Returns the new fullscreen flag, or None to quit."""
    if key in (ord("q"), 27):
        return None
    if key == ord(" "):
        if game.state in (State.MENU, State.OVER):
            game.start()
        else:
            game.toggle_pause()
    elif key == ord("f"):
        fullscreen = not fullscreen
        cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN,
                              cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
    return fullscreen


def main() -> int:
    parser = argparse.ArgumentParser(description="Slice fruit with your finger through the webcam.")
    parser.add_argument("--camera", type=int, default=0, help="camera index")
    parser.add_argument("--mute", action="store_true", help="no sound effects")
    parser.add_argument("--fullscreen", action="store_true", help="start fullscreen")
    parser.add_argument("--no-log", action="store_true", help="don't write fruit_slice/logs/")
    args = parser.parse_args()

    camera = TrackedCamera(args.camera)
    if not camera.ok:
        camera.close()
        print("Could not read from the camera. Allow camera access for this app in\n"
              "System Settings > Privacy & Security > Camera, or try --camera 1.",
              file=sys.stderr)
        return 1

    cfg = GameConfig()
    game = Game(cfg, best=load_best())
    hand = HandInput(cfg.width, cfg.height)
    sounds = Sounds(enabled=not args.mute)
    log = None if args.no_log else GameLog()
    if log:
        log.info(f"camera {args.camera}, canvas {cfg.width}x{cfg.height}, "
                 f"blade_min_speed {cfg.blade_min_speed:.0f}px/s, best {game.best}")
        print(f"Logging to {log.path} (+ .csv)")

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, cfg.width, cfg.height)
    fullscreen = False
    if args.fullscreen:
        fullscreen = handle_key(game, ord("f"), fullscreen)

    fps, last_t, seq = 0.0, time.monotonic(), 0
    camera.start()
    print("Orchard Blade running. Press q in the game window to quit.")
    try:
        while True:
            # One game step per tracked camera frame, timed by when it was captured.
            result = camera.next(seq)
            if result is None:  # camera stalled: keep the window responsive
                fullscreen = handle_key(game, cv2.waitKey(1) & 0xFF, fullscreen)
                if fullscreen is None:
                    break
                continue
            seq, frame, landmarks, now = result
            dt, last_t = now - last_t, now
            fps = 0.9 * fps + 0.1 / max(dt, 1e-6)

            h, w = frame.shape[:2]
            handle_hold(game, hand.update(landmarks, w / h, now))
            cutting = not hand.sheathed
            game.update(dt, hand.blade, cutting)
            if log:
                log.frame(now, dt, game, hand, cutting)
                for message in game.messages:
                    log.info(message)
            game.messages.clear()
            for event in game.events:
                sounds.play(event)
                if event == "over" and game.new_best:
                    save_best(game.best)
            game.events.clear()

            cv2.imshow(WINDOW, render.draw(frame, game, hand, now, fps))
            fullscreen = handle_key(game, cv2.waitKey(1) & 0xFF, fullscreen)
            if fullscreen is None or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        camera.close()
        if log:
            log.info("quit")
            log.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
