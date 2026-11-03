"""Gesture state machine: decides what each frame's hand features mean and
drives the Mac.

Each hand shape maps (in settings [poses]) to a mode, debounced over a few frames:
  move:   cursor follows the palm (the index tip if the shape is point);
          pinches run the pinch_* actions, or with point, tucking the thumb runs
          thumb_press ("left_click" = click/drag)
  scroll: move hand up/down to scroll
  swipe:  flicks run the swipe_* actions
  freeze: nothing happens (rest your hand)
or to an action, which runs once after the shape is held for pose_action_hold_s.
Defaults: open hand = move, two fingers = scroll, point = swipe, fist = freeze.
"""

import math
from collections import deque
from enum import Enum

from .filters import OneEuroFilter, OneEuroFilter2D
from .gestures import HandFeatures, Pose
from .mac import Mac
from .settings import Settings


class Mode(Enum):
    IDLE = "no hand"
    MOVE = "move"
    SCROLL = "scroll"
    SWIPE = "swipe"
    FREEZE = "freeze"
    ACTION = "action"  # holding a shape that's mapped to an action


SETTING_TO_MODE = {
    "move": Mode.MOVE,
    "scroll": Mode.SCROLL,
    "swipe": Mode.SWIPE,
    "freeze": Mode.FREEZE,
}


class Controller:
    def __init__(self, settings: Settings, mac: Mac, screen_w: float, screen_h: float):
        self.mac = mac
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.paused = False
        self._last_seen_t = -1e9

        self.mode = Mode.IDLE
        self._candidate: Pose | None = None
        self._candidate_frames = 0

        self.cursor = (screen_w / 2, screen_h / 2)
        self.left_down = False
        # Presses are keyed by finger ("index".."pinky" pinches, or "thumb").
        self._drag_finger: str | None = None  # press that holds the button down
        self._drag_active = False
        self._pinch_t = 0.0
        self._pinch_pos = (0.0, 0.0)
        self._latched: set[str] = set()  # one-shot presses waiting for release
        self._unarmed: set[str] = set()  # must be seen released before they count
        self._move_pose: Pose | None = None  # shape that put us in move mode

        self._scroll_filter = OneEuroFilter(1.5, 0.01)
        self._scroll_last_y: float | None = None
        self._scroll_remainder = 0.0

        self._swipe_hist: deque[tuple[float, float, float]] = deque()
        self._last_swipe_t = -1e9

        self._action_pose: Pose | None = None
        self._action_t = 0.0
        self._action_fired = False
        self.last_event = ""

        self.apply_settings(settings)

    def apply_settings(self, settings: Settings) -> None:
        self._release_buttons()
        self.settings = settings
        self.cfg = settings.config
        self._cursor_filter = OneEuroFilter2D(self.cfg.filter_min_cutoff, self.cfg.filter_beta)
        # Presses with no action are ignored, so a near-pinch can't freeze the cursor.
        self._pinch_fingers = [f for f in ("index", "middle", "ring", "pinky")
                               if settings.gestures[f"pinch_{f}"] != "none"]
        self._thumb_fingers = ["thumb"] if settings.gestures["thumb_press"] != "none" else []

    # ---------------------------------------------------------------- helpers

    def _to_screen(self, x: float, y: float) -> tuple[float, float]:
        l, t, r, b = self.cfg.active_box
        nx = min(max((x - l) / (r - l), 0.0), 1.0)
        ny = min(max((y - t) / (b - t), 0.0), 1.0)
        return nx * (self.screen_w - 1), ny * (self.screen_h - 1)

    def _steady(self, target: tuple[float, float]) -> tuple[float, float]:
        """Dead zone around the cursor: small movements are ignored; larger ones
        drag the cursor along, staying cursor_deadzone_px behind the target."""
        dx, dy = target[0] - self.cursor[0], target[1] - self.cursor[1]
        d = math.hypot(dx, dy)
        dz = self.cfg.cursor_deadzone_px
        if d <= dz:
            return self.cursor
        k = (d - dz) / d
        return self.cursor[0] + dx * k, self.cursor[1] + dy * k

    def _run(self, name: str, spec: str) -> None:
        if spec == "none":
            return
        self.settings.actions[name](self.mac, *self.cursor)
        self.last_event = f"{name}: {spec}"

    def _run_gesture(self, gesture: str) -> None:
        self._run(gesture, self.settings.gestures[gesture])

    def _press(self, f: HandFeatures, finger: str) -> tuple[str, float, float, float]:
        """(gesture name, distance, start threshold, release threshold)."""
        cfg = self.cfg
        if finger == "thumb":
            return "thumb_press", f.thumb_press, cfg.thumb_press_start, cfg.thumb_press_release
        return f"pinch_{finger}", f.pinch[finger], cfg.pinch_start, cfg.pinch_release

    def _release_buttons(self) -> None:
        if self.left_down:
            self.mac.left_up(*self.cursor)
            self.left_down = False
            self._drag_finger = None
            self._drag_active = False
        self._latched.clear()

    def _set_mode(self, mode: Mode) -> None:
        if mode == self.mode:
            return
        self._release_buttons()
        self.mode = mode
        self._move_pose = None
        # Fresh state for the new mode, so stale motion doesn't leak in.
        self._cursor_filter.reset()
        self._scroll_filter.reset()
        self._scroll_last_y = None
        self._scroll_remainder = 0.0
        self._swipe_hist.clear()

    def _apply_pose(self, pose: Pose, t: float) -> None:
        """Switch modes once a pose has held for a few frames. Shapes set to
        "none" (and unrecognized ones) leave the current mode alone."""
        if pose == self._candidate:
            self._candidate_frames += 1
        else:
            self._candidate, self._candidate_frames = pose, 1
        if self._candidate_frames < self.cfg.pose_stable_frames:
            return
        spec = self.settings.poses.get(pose.value, "none")
        if spec in SETTING_TO_MODE:
            self._set_mode(SETTING_TO_MODE[spec])
            if self.mode == Mode.MOVE and pose != self._move_pose:
                # Switching between move shapes can change what the cursor tracks.
                self._move_pose = pose
                self._cursor_filter.reset()
                self._latched.clear()
                # Don't click just because the hand arrived already pinched.
                self._unarmed = {"thumb", "index", "middle", "ring", "pinky"}
        elif spec != "none" and (self.mode != Mode.ACTION or self._action_pose != pose):
            self._set_mode(Mode.ACTION)
            self._action_pose = pose
            self._action_t = t
            self._action_fired = False

    # ------------------------------------------------------------------ main

    def update(self, f: HandFeatures | None, t: float) -> None:
        # Ride out brief tracking dropouts instead of dropping a drag.
        if f is None and not self.paused and t - self._last_seen_t < self.cfg.lost_hand_grace_s:
            return
        if self.paused or f is None:
            self._set_mode(Mode.IDLE)
            self._candidate = None
            return
        self._last_seen_t = t

        # Holding a pinch keeps us in MOVE even if the pose wobbles mid-drag.
        if not self.left_down:
            self._apply_pose(f.pose, t)

        if self.mode == Mode.MOVE:
            self._update_move(f, t)
        elif self.mode == Mode.SCROLL:
            self._update_scroll(f, t)
        elif self.mode == Mode.SWIPE:
            self._update_swipe(f, t)
        elif self.mode == Mode.ACTION:
            self._update_action(t)

    def _update_move(self, f: HandFeatures, t: float) -> None:
        cfg = self.cfg
        pointing = self._move_pose == Pose.POINT
        anchor = f.index_tip if pointing else f.palm
        target = self._steady(self._cursor_filter(*self._to_screen(*anchor), t))

        # Held left button: release when the fingers separate.
        if self.left_down:
            _, dist, _, release = self._press(f, self._drag_finger)
            if dist > release:
                self.mac.left_up(*self.cursor)
                self.left_down = False
                self._drag_finger = None
                self._drag_active = False

        if self.left_down:
            # Hold the cursor still briefly so a quick pinch is a clean click.
            if not self._drag_active:
                moved = math.dist(target, self._pinch_pos)
                if moved > cfg.drag_deadzone_px or t - self._pinch_t > cfg.drag_hold_s:
                    self._drag_active = True
            if self._drag_active and target != self.cursor:
                self.cursor = target
                self.mac.left_drag(*self.cursor)
            return

        # Pointing: only the thumb press counts (curled fingers sit near the thumb).
        fingers = self._thumb_fingers if pointing else self._pinch_fingers
        presses = {fin: self._press(f, fin) for fin in fingers}
        released = {fin for fin, (_, d, _, rel) in presses.items() if d > rel}
        self._latched -= released
        self._unarmed -= released

        # New press: the closest armed one under its threshold wins.
        candidates = [fin for fin, (_, d, start, _) in presses.items()
                      if d < start and fin not in self._latched and fin not in self._unarmed]
        if candidates and not self._latched:
            finger = min(candidates, key=lambda fin: presses[fin][1])
            gesture = presses[finger][0]
            if self.settings.gestures[gesture] == "left_click":
                self.left_down = True
                self._drag_finger = finger
                self._drag_active = False
                self._pinch_t = t
                self._pinch_pos = self.cursor
                self.mac.left_down(*self.cursor)
                self.last_event = f"{gesture}: left_click"
                return
            self._latched.add(finger)
            self._run_gesture(gesture)

        # Keep the cursor still while a one-shot pinch is held.
        if not self._latched and target != self.cursor:
            self.cursor = target
            self.mac.move(*self.cursor)

    def _update_scroll(self, f: HandFeatures, t: float) -> None:
        y = self._scroll_filter(f.palm[1], t)
        if self._scroll_last_y is not None:
            # Hand up (y decreases) -> negative wheel -> page content moves up.
            dy = (y - self._scroll_last_y) * self.cfg.scroll_gain
            if self.cfg.scroll_invert:
                dy = -dy
            dy += self._scroll_remainder
            whole = int(dy)
            self._scroll_remainder = dy - whole
            self.mac.scroll(whole)
        self._scroll_last_y = y

    def _update_swipe(self, f: HandFeatures, t: float) -> None:
        cfg = self.cfg
        x, y = f.index_tip
        hist = self._swipe_hist
        hist.append((t, x, y))
        while hist and t - hist[0][0] > cfg.swipe_window_s:
            hist.popleft()
        if t - self._last_swipe_t < cfg.swipe_cooldown_s or len(hist) < 3:
            return

        dx = x - hist[0][1]
        dy = y - hist[0][2]
        if max(abs(dx), abs(dy)) < cfg.swipe_min_distance:
            return

        if abs(dx) > 1.5 * abs(dy):
            self._run_gesture("swipe_left" if dx < 0 else "swipe_right")
        elif abs(dy) > 1.5 * abs(dx):
            self._run_gesture("swipe_up" if dy < 0 else "swipe_down")
        else:
            return  # diagonal: ignore
        self._last_swipe_t = t
        hist.clear()

    def _update_action(self, t: float) -> None:
        # Fire once per hold; make a different shape to fire again.
        if not self._action_fired and t - self._action_t >= self.cfg.pose_action_hold_s:
            self._action_fired = True
            name = self._action_pose.value
            self._run(name, self.settings.poses[name])

    def close(self) -> None:
        self._release_buttons()
