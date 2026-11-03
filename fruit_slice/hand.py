"""Turns the tracked hand into game input: the blade (index fingertip in
canvas pixels), its trail, the current hand shape, and "hold a shape" commands."""

import math
from collections import deque

from gesture_control.config import Config
from gesture_control.filters import OneEuroFilter
from gesture_control.gestures import (INDEX_MCP, INDEX_TIP, MIDDLE_MCP, THUMB_TIP, WRIST,
                                      Pose, extract_features)

# Part of the (mirrored) camera image that maps to the whole canvas, so the
# edges can be reached without the hand leaving the frame. (left, top, right, bottom)
REACH_BOX = (0.08, 0.08, 0.92, 0.92)

# In a fast swipe, motion blur makes the tracker misread the pointing finger as
# curled for a frame or two, putting the fingertip on the palm 150-250 px below
# where it is, so the trail dipped into a V. On such frames the blade is placed at
# the knuckle plus the last good knuckle-to-tip offset. A frame counts as misread
# when the index reads as curled, or its tip is suddenly this much closer to the
# knuckle than usual...
SHORT_FINGER = 0.7
# ...unless it stays short this many frames (then the hand really moved away).
MAX_SHORT_FRAMES = 3
# A fist sheathes the blade only once seen this many frames in a row, so a
# misread mid-swipe doesn't stop the cut.
SHEATHE_FRAMES = 4

THUMB_POINTS = (1, 2, 3, 4)
# Thumbs up: the thumb tip is at least this many palm sizes above the rest of the hand.
THUMB_UP_MARGIN = 0.3


def is_thumbs_up(landmarks, aspect: float) -> bool:
    """A looser thumbs up than gesture_control's: the thumb tip sits clearly
    above every other point of the hand. That holds however the fist is turned,
    while the finger-extension check often misreads a sideways fist."""
    wrist, mcp = landmarks[WRIST], landmarks[MIDDLE_MCP]
    palm = math.hypot((wrist.x - mcp.x) * aspect, wrist.y - mcp.y)
    top_of_rest = min(p.y for i, p in enumerate(landmarks) if i not in THUMB_POINTS)
    return landmarks[THUMB_TIP].y < top_of_rest - THUMB_UP_MARGIN * palm


class PointFilter:
    """One Euro filter for a 2D point where both axes share one cutoff, set by
    the point's speed (direction ignored). gesture_control's OneEuroFilter2D
    adapts each axis on its own signed speed: in a fast left-right swipe y
    barely moves, and x's speed averages out as it reverses, so both stayed
    heavily smoothed and lagged behind the finger, drawing a V instead of a line."""

    def __init__(self, min_cutoff: float = 1.5, beta: float = 0.03, d_cutoff: float = 4.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self) -> None:
        self._p: tuple[float, float] | None = None
        self._t = 0.0
        self._speed = 0.0

    def __call__(self, x: float, y: float, t: float) -> tuple[float, float]:
        if self._p is None or t <= self._t:
            self._p, self._t = (x, y), t
            return self._p
        dt = t - self._t
        px, py = self._p
        a_d = OneEuroFilter._alpha(self.d_cutoff, dt)
        self._speed = a_d * math.hypot(x - px, y - py) / dt + (1 - a_d) * self._speed
        a = OneEuroFilter._alpha(self.min_cutoff + self.beta * self._speed, dt)
        self._p, self._t = (a * x + (1 - a) * px, a * y + (1 - a) * py), t
        return self._p


class HandInput:
    def __init__(self, width: int, height: int, hold_s: float = 0.8,
                 trail_s: float = 0.12, stable_frames: int = 3):
        self.width, self.height = width, height
        self.hold_s = hold_s
        self.trail_s = trail_s
        self.stable_frames = stable_frames
        self._cfg = Config()
        # Light smoothing only: the blade has to keep up with fast swipes.
        self._filter = PointFilter()
        self.raw: tuple[float, float] | None = None    # fingertip as tracked, for the log
        self.blade: tuple[float, float] | None = None  # smoothed blade point
        self.estimated = False  # blade placed from the knuckle this frame (finger misread)
        self.pose: Pose | None = None
        self.sheathed = False
        self._finger: tuple[float, float] | None = None  # last good knuckle -> tip offset
        self._finger_len = 0.0
        self._short_frames = 0
        self._fist_frames = 0
        self.trail: deque[tuple[float, float, float]] = deque()  # (x, y, t)
        self.hold_pose: Pose | None = None
        self.hold_progress = 0.0  # 0..1 toward firing hold_pose
        self._hold_start = 0.0
        self._fired = False
        self._candidate: Pose | None = None
        self._candidate_frames = 0

    def update(self, landmarks, aspect: float, now: float) -> Pose | None:
        """Feed one frame's landmarks (or None). Returns a pose once, when it
        has been held for hold_s."""
        if landmarks is None:
            self.raw = self.blade = self.pose = self.hold_pose = self._finger = None
            self.hold_progress, self.estimated, self.sheathed = 0.0, False, False
            self._fist_frames = 0
            self._filter.reset()
            self.trail.clear()
            return None

        f = extract_features(landmarks, aspect, self._cfg)
        self.raw = self._to_canvas(landmarks[INDEX_TIP])
        point, self.estimated = self._blade_point(landmarks, not f.extended["index"])
        self.blade = self._filter(*point, now)
        self.pose = Pose.THUMBS_UP if is_thumbs_up(landmarks, aspect) else f.pose
        self._fist_frames = self._fist_frames + 1 if self.pose is Pose.FIST else 0
        self.sheathed = self._fist_frames >= SHEATHE_FRAMES
        self.trail.append((*self.blade, now))
        while self.trail and now - self.trail[0][2] > self.trail_s:
            self.trail.popleft()
        return self._update_hold(self.pose, now)

    def _to_canvas(self, lm) -> tuple[float, float]:
        l, t, r, b = REACH_BOX
        return (lm.x - l) / (r - l) * self.width, (lm.y - t) / (b - t) * self.height

    def _blade_point(self, landmarks, curled: bool) -> tuple[tuple[float, float], bool]:
        """The fingertip, or knuckle + last good offset when the finger is misread
        (see SHORT_FINGER). Returns (point, estimated)."""
        tip = self.raw
        knuckle = self._to_canvas(landmarks[INDEX_MCP])
        offset = (tip[0] - knuckle[0], tip[1] - knuckle[1])
        length = math.hypot(*offset)
        short = self._finger is not None and length < SHORT_FINGER * self._finger_len
        if short and not curled:
            self._short_frames += 1
            short = self._short_frames <= MAX_SHORT_FRAMES
        else:
            self._short_frames = 0
        if self._finger is not None and (curled or short):
            return (knuckle[0] + self._finger[0], knuckle[1] + self._finger[1]), True
        self._finger = offset
        self._finger_len = length if not self._finger_len else 0.7 * self._finger_len + 0.3 * length
        return tip, False

    def _update_hold(self, pose: Pose, now: float) -> Pose | None:
        # A new shape must be seen a few frames in a row before the hold restarts,
        # so one misread frame doesn't reset it.
        if pose is not self.hold_pose:
            if pose is self._candidate:
                self._candidate_frames += 1
            else:
                self._candidate, self._candidate_frames = pose, 1
            if self._candidate_frames >= self.stable_frames or self.hold_pose is None:
                self.hold_pose, self._hold_start, self._fired = pose, now, False
        else:
            self._candidate, self._candidate_frames = None, 0

        held = now - self._hold_start
        self.hold_progress = 0.0 if self._fired else min(1.0, held / self.hold_s)
        if not self._fired and held >= self.hold_s:
            self._fired = True
            return self.hold_pose
        return None
