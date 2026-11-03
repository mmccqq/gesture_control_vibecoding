"""Tunable settings (defaults; settings.toml [tuning] overrides them). Distances are normalized: image coords are 0..1, and pinch
distances are divided by palm size so they don't depend on how far you sit."""

from dataclasses import dataclass


@dataclass
class Config:
    # Camera
    camera_index: int = 0
    frame_width: int = 640
    frame_height: int = 480
    # Show the camera image in the preview window (False = hand skeleton on black).
    preview_camera_image: bool = False

    # Region of the (mirrored) camera image that maps to the full screen.
    # Smaller box = less arm movement needed. (left, top, right, bottom)
    active_box: tuple[float, float, float, float] = (0.25, 0.20, 0.75, 0.65)

    # One Euro filter for cursor smoothing: lower min_cutoff = smoother but
    # laggier when still; higher beta = less lag when moving fast (too high and
    # hand tremor counts as "fast", so the shaking gets through).
    filter_min_cutoff: float = 0.8
    filter_beta: float = 0.005
    # The cursor ignores movement within this radius (screen pixels) and is
    # pulled along like on a leash beyond it, so tremor doesn't shake it.
    cursor_deadzone_px: float = 8.0

    # A pose must be seen this many frames in a row before the mode switches.
    pose_stable_frames: int = 3

    # Keep the current mode (and any held drag) if the hand vanishes this briefly.
    lost_hand_grace_s: float = 0.25

    # Finger counts as extended when wrist->tip > wrist->PIP * this ratio.
    finger_extended_ratio: float = 1.1
    # Thumbs-up: thumb tip at least this far (in palm sizes) from the index knuckle.
    thumb_extended_ratio: float = 0.8

    # A hand shape mapped to an action fires once after being held this long.
    pose_action_hold_s: float = 0.5

    # Pinch thresholds (thumb tip to finger tip / palm size), with hysteresis.
    pinch_start: float = 0.28
    pinch_release: float = 0.40

    # Thumb press while pointing (thumb tip to the side of the hand / palm size).
    thumb_press_start: float = 0.40
    thumb_press_release: float = 0.55

    # While pinched, the cursor stays put until you move this far or hold this
    # long, so a quick pinch is a clean click instead of a tiny drag.
    drag_deadzone_px: float = 15.0
    drag_hold_s: float = 0.30

    # Scroll mode: screen pixels scrolled per full-frame-height hand movement.
    scroll_gain: float = 3000.0
    # False = "natural" (hand up pushes the page up, like a trackpad).
    scroll_invert: bool = False

    # Swipe detection (pointing pose).
    swipe_window_s: float = 0.35
    swipe_min_distance: float = 0.18  # fraction of frame
    swipe_cooldown_s: float = 0.9
