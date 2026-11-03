"""Gesture logic tests using synthetic hands (no camera needed).
Run:  .venv/bin/python -m unittest discover tests"""

import unittest
from types import SimpleNamespace

import math
import tempfile
from pathlib import Path

from gesture_control.controller import Controller, Mode
from gesture_control.gestures import Pose, extract_features
from gesture_control.settings import POSES, Settings, SettingsError, load_settings

FINGER_X = {"index": -0.05, "middle": 0.0, "ring": 0.04, "pinky": 0.08}
FINGER_MCP = {"index": 5, "middle": 9, "ring": 13, "pinky": 17}


def fake_hand(extended=("index", "middle", "ring", "pinky"), pinch=None, dx=0.0, dy=0.0,
              thumb_up=False, thumb_tucked=False):
    """Upright hand with the wrist near (0.5, 0.8). `pinch` puts the thumb tip
    on that finger's tip; `thumb_up` points the thumb straight up."""
    pts = [(0.0, 0.0)] * 21
    wx, wy = 0.5 + dx, 0.8 + dy
    pts[0] = (wx, wy)
    for name, mcp in FINGER_MCP.items():
        x, my = wx + FINGER_X[name], wy - 0.15
        pts[mcp] = (x, my)
        if name in extended:
            pts[mcp + 1], pts[mcp + 2], pts[mcp + 3] = (x, my - 0.05), (x, my - 0.09), (x, my - 0.13)
        else:
            pts[mcp + 1], pts[mcp + 2], pts[mcp + 3] = (x, my - 0.04), (x, my - 0.01), (x, my + 0.03)
    # Thumb out to the side.
    pts[1], pts[2], pts[3], pts[4] = (wx - 0.06, wy - 0.03), (wx - 0.10, wy - 0.07), (wx - 0.13, wy - 0.10), (wx - 0.16, wy - 0.12)
    if pinch:
        pts[4] = pts[FINGER_MCP[pinch] + 3]
    if thumb_tucked:
        pts[4] = (wx - 0.03, wy - 0.15)  # against the index knuckle
    if thumb_up:
        pts[3], pts[4] = (wx - 0.08, wy - 0.22), (wx - 0.08, wy - 0.30)
    return [SimpleNamespace(x=x, y=y) for x, y in pts]


class FakeMac:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a: self.calls.append(name)

    def names(self):
        return [c for c in self.calls if c not in ("move", "left_drag", "scroll")]


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.cfg = self.settings.config
        self.mac = FakeMac()
        self.ctrl = Controller(self.settings, self.mac, 1920, 1080)
        self.t = 0.0

    def remap(self, **gestures):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.toml"
            poses = "\n".join(f'{k} = "{v}"' for k, v in gestures.items() if k in POSES)
            other = "\n".join(f'{k} = "{v}"' for k, v in gestures.items() if k not in POSES)
            path.write_text(f"[poses]\n{poses}\n[gestures]\n{other}\n")
            self.ctrl.apply_settings(load_settings(path))

    def feed(self, frames=1, **hand):
        for _ in range(frames):
            self.t += 1 / 30
            f = extract_features(fake_hand(**hand), 4 / 3, self.ctrl.cfg)
            self.ctrl.update(f, self.t)
        return f

    def test_poses(self):
        self.assertEqual(self.feed().pose, Pose.OPEN)
        self.assertEqual(self.feed(extended=("index",)).pose, Pose.POINT)
        self.assertEqual(self.feed(extended=("index", "middle")).pose, Pose.TWO_FINGERS)
        self.assertEqual(self.feed(extended=("index", "pinky")).pose, Pose.ROCK)
        self.assertEqual(self.feed(extended=()).pose, Pose.FIST)
        self.assertEqual(self.feed(extended=(), thumb_up=True).pose, Pose.THUMBS_UP)

    def test_open_hand_moves_cursor(self):
        self.feed(5)
        self.assertEqual(self.ctrl.mode, Mode.MOVE)
        self.assertIn("move", self.mac.calls)

    def test_pinch_is_click(self):
        self.feed(5)
        self.feed(2, extended=("middle", "ring", "pinky"), pinch="index")
        self.feed(2)
        self.assertEqual(self.mac.names(), ["left_down", "left_up"])

    def test_held_pinch_drags(self):
        self.feed(5)
        for i in range(20):
            self.feed(extended=("middle", "ring", "pinky"), pinch="index", dx=0.01 * i)
        self.assertTrue(self.ctrl.left_down)
        self.assertIn("left_drag", self.mac.calls)
        self.feed(2)
        self.assertFalse(self.ctrl.left_down)

    def test_middle_pinch_is_right_click_once(self):
        self.feed(5)
        self.feed(5, extended=("index", "ring", "pinky"), pinch="middle")
        self.feed(2)
        self.assertEqual(self.mac.names(), ["right_click"])

    def test_fist_does_not_click(self):
        self.feed(5, extended=(), pinch="index")
        self.assertEqual(self.ctrl.mode, Mode.FREEZE)
        self.assertEqual(self.mac.calls, [])

    def test_victory_scrolls(self):
        for i in range(10):
            self.feed(extended=("index", "middle"), dy=-0.01 * i)
        self.assertEqual(self.ctrl.mode, Mode.SCROLL)
        self.assertIn("scroll", self.mac.calls)

    def test_point_swipes(self):
        self.feed(5, extended=("index",))
        for i in range(8):
            self.feed(extended=("index",), dx=-0.04 * i)
        self.assertEqual(self.ctrl.last_event, "swipe_left: desktop_right")

        self.t += 1.0  # past cooldown
        self.feed(3, extended=("index",), dy=0.0)
        for i in range(8):
            self.feed(extended=("index",), dy=-0.04 * i)
        self.assertEqual(self.ctrl.last_event, "swipe_up: mission_control")
        self.assertEqual(self.mac.names(), ["key", "key"])

    def test_lost_hand_releases_drag_after_grace(self):
        self.feed(5)
        self.feed(15, extended=("middle", "ring", "pinky"), pinch="index")
        self.t += 0.1
        self.ctrl.update(None, self.t)
        self.assertTrue(self.ctrl.left_down)  # brief dropout tolerated
        self.t += 0.5
        self.ctrl.update(None, self.t)
        self.assertFalse(self.ctrl.left_down)
        self.assertEqual(self.mac.names()[-1], "left_up")

    def test_remapped_pinch_runs_action_once_without_drag(self):
        self.remap(pinch_index="play_pause", pinch_ring="keys:cmd+tab")
        self.feed(5)
        self.feed(10, extended=("middle", "ring", "pinky"), pinch="index")
        self.feed(3)
        self.feed(3, extended=("index", "middle", "pinky"), pinch="ring")
        self.feed(2)
        self.assertEqual(self.mac.names(), ["media_key", "key"])
        self.assertFalse(self.ctrl.left_down)

    def test_unmapped_pinch_is_ignored(self):
        self.remap(pinch_middle="none")
        self.feed(5)
        self.feed(5, extended=("index", "ring", "pinky"), pinch="middle")
        self.assertEqual(self.mac.names(), [])
        self.assertIn("move", self.mac.calls)  # cursor didn't freeze

    def test_remapped_swipe(self):
        self.remap(swipe_left="open:Safari")
        self.feed(5, extended=("index",))
        for i in range(8):
            self.feed(extended=("index",), dx=-0.04 * i)
        self.assertEqual(self.mac.names(), ["open_app"])

    def test_remapped_shapes(self):
        self.remap(fist="move", open_hand="scroll")
        self.feed(5, extended=())
        self.assertEqual(self.ctrl.mode, Mode.MOVE)
        self.feed(5)
        self.assertEqual(self.ctrl.mode, Mode.SCROLL)

    def test_shape_action_fires_once_after_hold(self):
        self.remap(thumbs_up="play_pause")
        self.feed(5, extended=(), thumb_up=True)  # ~0.17s: not held long enough yet
        self.assertEqual(self.mac.names(), [])
        self.feed(30, extended=(), thumb_up=True)  # held 1s+
        self.assertEqual(self.mac.names(), ["media_key"])
        self.feed(5)  # change shape, then do it again
        self.feed(30, extended=(), thumb_up=True)
        self.assertEqual(self.mac.names(), ["media_key", "media_key"])

    def test_none_shape_keeps_current_mode(self):
        self.remap(fist="none")
        self.feed(5)
        self.feed(5, extended=())
        self.assertEqual(self.ctrl.mode, Mode.MOVE)

    def test_point_moves_cursor_with_fingertip(self):
        self.remap(point="move")
        self.feed(5, extended=("index",))
        self.assertEqual(self.ctrl.mode, Mode.MOVE)
        before = self.ctrl.cursor
        # Same palm position, fingertip moved: the cursor must follow the tip.
        for _ in range(10):
            hand = fake_hand(extended=("index",))
            hand[8] = SimpleNamespace(x=hand[8].x + 0.1, y=hand[8].y)
            self.t += 1 / 30
            self.ctrl.update(extract_features(hand, 4 / 3, self.ctrl.cfg), self.t)
        self.assertGreater(self.ctrl.cursor[0], before[0] + 100)

    def test_point_thumb_tuck_clicks_and_ignores_pinches(self):
        self.remap(point="move")
        self.feed(5, extended=("index",))
        self.feed(3, extended=("index",), thumb_tucked=True)
        self.feed(3, extended=("index",))
        self.assertEqual(self.mac.names(), ["left_down", "left_up"])
        self.feed(5, extended=("index",), pinch="middle")  # curled middle near thumb
        self.assertEqual(self.mac.names(), ["left_down", "left_up"])

    def test_arriving_already_pressed_does_not_click(self):
        self.remap(point="move")
        self.feed(10, extended=("index",), thumb_tucked=True)
        self.assertEqual(self.mac.names(), [])
        self.assertIn("move", self.mac.calls)  # still moves while unarmed
        self.feed(3, extended=("index",))
        self.feed(3, extended=("index",), thumb_tucked=True)
        self.assertEqual(self.mac.names(), ["left_down"])

    def test_tremor_does_not_move_cursor(self):
        self.remap(point="move")
        self.feed(30, extended=("index",))  # settle

        def shake(frames):  # fingertip shakes ~2px of camera image every frame
            for i in range(frames):
                hand = fake_hand(extended=("index",))
                jitter = 0.003 if i % 2 else -0.003
                hand[8] = SimpleNamespace(x=hand[8].x + jitter, y=hand[8].y - jitter)
                self.t += 1 / 30
                self.ctrl.update(extract_features(hand, 4 / 3, self.ctrl.cfg), self.t)

        before = self.ctrl.cursor
        shake(10)  # the cursor rests at the dead zone's edge, so it may nudge once
        self.assertLess(math.dist(before, self.ctrl.cursor), 4)
        settled = self.ctrl.cursor
        moves = self.mac.calls.count("move")
        shake(60)
        self.assertEqual(self.ctrl.cursor, settled)
        self.assertEqual(self.mac.calls.count("move"), moves)


class SettingsTest(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.toml"
            path.write_text(text)
            return load_settings(path)

    def test_creates_default_file_that_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.toml"
            s = load_settings(path)
            self.assertTrue(path.exists())
            self.assertEqual(s.gestures, Settings().gestures)
            self.assertEqual(s.config, Settings().config)

    def test_overrides(self):
        s = self.load('[gestures]\nswipe_up = "keys:cmd+space"\n'
                      '[tuning]\nactive_box = [0.3, 0.2, 0.7, 0.6]\nscroll_gain = 1000\n')
        self.assertEqual(s.gestures["swipe_up"], "keys:cmd+space")
        self.assertEqual(s.gestures["swipe_down"], "app_windows")  # untouched default
        self.assertEqual(s.config.active_box, (0.3, 0.2, 0.7, 0.6))
        self.assertEqual(s.config.scroll_gain, 1000.0)

    def test_errors(self):
        for text in ['[gestures]\nwave = "mute"',
                     '[poses]\nopen_hand = "fly"',
                     '[poses]\nspock = "move"',
                     '[gestures]\nswipe_up = "teleport"',
                     '[gestures]\nswipe_up = "keys:cmd+banana"',
                     '[tuning]\nscroll_gain = "fast"',
                     '[tuning]\nactive_box = [1, 2]',
                     '[gestures\n']:
            with self.assertRaises(SettingsError, msg=text):
                self.load(text)


if __name__ == "__main__":
    unittest.main()
