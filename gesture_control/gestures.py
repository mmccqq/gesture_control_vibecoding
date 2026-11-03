"""Turn 21 MediaPipe hand landmarks into simple features: which fingers are
extended, the hand pose, and pinch distances."""

import math
from dataclasses import dataclass
from enum import Enum

from .config import Config

# MediaPipe hand landmark indices
WRIST = 0
THUMB_TIP = 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_MCP, RING_PIP, RING_TIP = 13, 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20

FINGERS = {
    "index": (INDEX_PIP, INDEX_TIP),
    "middle": (MIDDLE_PIP, MIDDLE_TIP),
    "ring": (RING_PIP, RING_TIP),
    "pinky": (PINKY_PIP, PINKY_TIP),
}
PALM_POINTS = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)

Point = tuple[float, float]


class Pose(Enum):
    # Values are the names used in settings.toml [poses].
    OPEN = "open_hand"           # 3+ fingers extended
    POINT = "point"              # index only
    TWO_FINGERS = "two_fingers"  # index + middle
    ROCK = "rock"                # index + pinky
    FIST = "fist"                # nothing extended
    THUMBS_UP = "thumbs_up"      # fist with the thumb pointing up
    OTHER = "other"              # anything else: never changes the mode


@dataclass
class HandFeatures:
    palm: Point          # normalized image coords (0..1)
    index_tip: Point
    extended: dict[str, bool]
    thumb_up: bool
    pinch: dict[str, float]  # finger -> thumb-to-fingertip distance / palm size
    thumb_press: float       # thumb tip to the side of the hand / palm size ("finger gun")
    pose: Pose


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def classify_pose(ext: dict[str, bool], thumb_up: bool) -> Pose:
    n = sum(ext.values())
    if n == 0:
        return Pose.THUMBS_UP if thumb_up else Pose.FIST
    if ext["index"] and n == 1:
        return Pose.POINT
    if ext["index"] and ext["middle"] and n == 2:
        return Pose.TWO_FINGERS
    if ext["index"] and ext["pinky"] and n == 2:
        return Pose.ROCK
    if n >= 3:
        return Pose.OPEN
    return Pose.OTHER


def extract_features(landmarks, aspect: float, cfg: Config) -> HandFeatures:
    """`landmarks` is a list of 21 objects with .x/.y in 0..1. `aspect` is
    width/height, used so distances aren't stretched on non-square frames."""
    # Work in a space where x and y have the same scale (units of frame height).
    pts = [(lm.x * aspect, lm.y) for lm in landmarks]

    wrist = pts[WRIST]
    ext = {
        name: _dist(wrist, pts[tip]) > _dist(wrist, pts[pip]) * cfg.finger_extended_ratio
        for name, (pip, tip) in FINGERS.items()
    }

    palm_size = max(_dist(wrist, pts[MIDDLE_MCP]), 1e-6)
    # Thumb sticks out away from the knuckles and its tip is above them.
    thumb_up = (_dist(pts[THUMB_TIP], pts[INDEX_MCP]) / palm_size > cfg.thumb_extended_ratio
                and pts[THUMB_TIP][1] < pts[INDEX_MCP][1])
    palm_x = sum(landmarks[i].x for i in PALM_POINTS) / len(PALM_POINTS)
    palm_y = sum(landmarks[i].y for i in PALM_POINTS) / len(PALM_POINTS)

    return HandFeatures(
        palm=(palm_x, palm_y),
        index_tip=(landmarks[INDEX_TIP].x, landmarks[INDEX_TIP].y),
        extended=ext,
        thumb_up=thumb_up,
        pinch={name: _dist(pts[THUMB_TIP], pts[tip]) / palm_size
               for name, (_, tip) in FINGERS.items()},
        # Closest of the spots a tucked thumb lands on while pointing.
        thumb_press=min(_dist(pts[THUMB_TIP], pts[i])
                        for i in (INDEX_MCP, INDEX_PIP, MIDDLE_PIP)) / palm_size,
        pose=classify_pose(ext, thumb_up),
    )
