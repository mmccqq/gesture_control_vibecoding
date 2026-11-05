"""Game logic tests with synthetic blade input (no camera needed).
Run from the project root:  .venv/bin/python -m unittest discover -s fruit_slice/tests -t ."""

import math
import random
import unittest
from types import SimpleNamespace

from fruit_slice.game import FROST, FRUITS, THORN, Game, Item, State, segment_hits_circle
from fruit_slice.hand import HandInput, PointFilter, is_thumbs_up
from gesture_control.gestures import Pose

APPLE = FRUITS[0]
DT = 1 / 30


class GameTest(unittest.TestCase):
    def setUp(self):
        self.game = Game(rng=random.Random(1))
        self.game.start()
        self.game.events.clear()
        self.game._next_spawn = 1e9  # only the items each test places

    def place(self, type_=APPLE, x=480.0, y=360.0):
        item = Item(type_, x, y, 0.0, 0.0)
        self.game.items.append(item)
        return item

    def swipe(self, y=360.0, x0=300.0, x1=700.0, steps=4):
        """A fast horizontal swipe through y, then the blade rests so the stroke ends."""
        for i in range(steps + 1):
            self.game.update(DT, (x0 + (x1 - x0) * i / steps, y))
        for _ in range(10):
            self.game.update(DT, (x1, y))

    def test_segment_hits_circle(self):
        self.assertTrue(segment_hits_circle((0, 0), (10, 0), (5, 3), 4))
        self.assertFalse(segment_hits_circle((0, 0), (10, 0), (5, 5), 4))
        self.assertTrue(segment_hits_circle((0, 0), (10, 0), (12, 0), 3))  # past the end
        self.assertFalse(segment_hits_circle((0, 0), (10, 0), (15, 0), 3))

    def test_fast_swipe_slices_fruit(self):
        self.place()
        self.swipe()
        self.assertEqual(self.game.items, [])
        self.assertEqual(len(self.game.halves), 2)
        self.assertEqual(self.game.score, 1)
        self.assertIn("slice", self.game.events)

    def test_slow_blade_does_not_cut(self):
        self.place()
        for i in range(60):
            self.game.update(DT, (300 + i * 7, 360))  # ~210 px/s
        self.assertEqual(self.game.score, 0)
        self.assertEqual(self.game.halves, [])

    def test_sheathed_blade_does_not_cut(self):
        self.place()
        for i in range(5):
            self.game.update(DT, (300 + i * 100, 360), cutting=False)
        self.assertEqual(self.game.score, 0)

    def test_combo_for_three_in_one_stroke(self):
        for x in (380, 480, 580):
            self.place(x=x)
        self.swipe()
        self.assertEqual(self.game.score, 3 + 3)
        self.assertIn("combo", self.game.events)

    def test_two_in_one_stroke_is_not_a_combo(self):
        for x in (380, 580):
            self.place(x=x)
        self.swipe()
        self.assertEqual(self.game.score, 2)
        self.assertNotIn("combo", self.game.events)

    def test_thorn_costs_a_life_and_streak(self):
        self.game.streak = 5
        self.place(THORN)
        self.swipe()
        self.assertEqual(self.game.lives, 2)
        self.assertEqual(self.game.streak, 0)
        self.assertEqual(self.game.score, 0)

    def test_missed_fruit_costs_a_life(self):
        item = self.place(y=self.game.cfg.height + 100)
        item.vy = 10.0
        self.game.update(DT, None)
        self.assertEqual(self.game.lives, 2)
        self.assertIn("miss", self.game.events)

    def test_falling_thorn_is_harmless(self):
        item = self.place(THORN, y=self.game.cfg.height + 100)
        item.vy = 10.0
        self.game.update(DT, None)
        self.assertEqual(self.game.lives, 3)

    def test_frost_slows_time(self):
        self.place(FROST)
        self.swipe()
        self.assertGreater(self.game.frost_left, 0)
        self.assertLess(self.game.time_scale, 1.0)

    def test_streak_raises_multiplier(self):
        self.game.streak = self.game.cfg.streak_per_multiplier
        self.assertEqual(self.game.multiplier, 2)
        self.place()
        self.swipe()
        self.assertEqual(self.game.score, 2)

    def test_game_over_records_best(self):
        self.game.score = 7
        for _ in range(3):
            self.place(THORN)
            self.swipe()
        self.assertIs(self.game.state, State.OVER)
        self.assertEqual(self.game.best, 7)
        self.assertTrue(self.game.new_best)

    def test_menu_slicing_scores_nothing(self):
        game = Game(rng=random.Random(1))
        game._next_spawn = 1e9
        game.items.append(Item(APPLE, 480, 360, 0, 0))
        for i in range(5):
            game.update(DT, (300 + i * 100, 360))
        self.assertEqual(game.score, 0)
        self.assertEqual(len(game.halves), 2)

    def test_pause_freezes_items(self):
        item = self.place()
        self.game.toggle_pause()
        self.game.update(DT, None)
        self.assertEqual((item.y, item.vy), (360.0, 0.0))

    def test_spawning_launches_items_upward(self):
        self.game._next_spawn = 0.0
        for _ in range(20):
            self.game.update(DT, None)
        self.assertTrue(self.game.items)
        self.assertTrue(all(i.y < self.game.cfg.height + i.type.radius for i in self.game.items))


class PointFilterTest(unittest.TestCase):
    def test_follows_fast_back_and_forth_swipe(self):
        """A 4 Hz left-right swipe: the old per-axis filter lagged ~20 px behind."""
        f, rng, errors = PointFilter(), random.Random(0), []
        for i in range(90):
            t = i / 30
            x = 480 + 280 * math.sin(2 * math.pi * 4 * t)
            fx, fy = f(x + rng.gauss(0, 2), 360 + rng.gauss(0, 2), t)
            if i > 15:
                errors.append(math.hypot(fx - x, fy - 360))
        self.assertLess(sum(errors) / len(errors), 8)

    def test_smooths_a_still_hand(self):
        f, rng, xs = PointFilter(), random.Random(1), []
        for i in range(90):
            xs.append(f(480 + rng.gauss(0, 2), 360, i / 30)[0])
        self.assertLess(max(xs[30:]) - min(xs[30:]), 6)


def fake_hand(fist=False, thumb_up=False):
    """Upright hand near the frame centre, open by default."""
    pts = [(0.5, 0.8)] + [(0.0, 0.0)] * 20
    for i, (x, mcp) in enumerate(((-0.05, 5), (0.0, 9), (0.04, 13), (0.08, 17))):
        fx, my = 0.5 + x, 0.65
        pts[mcp] = (fx, my)
        tail = ((0.04, 0.01, -0.03) if fist else (0.05, 0.09, 0.13))
        for j, d in enumerate(tail, 1):
            pts[mcp + j] = (fx, my - d)
    pts[1:5] = [(0.44, 0.77), (0.40, 0.73), (0.37, 0.70), (0.34, 0.68)]
    if thumb_up:
        pts[3], pts[4] = (0.42, 0.58), (0.42, 0.50)
    return [SimpleNamespace(x=x, y=y) for x, y in pts]


def sideways_thumbs_up():
    """Fist turned sideways (knuckles stacked vertically) with the thumb up. The
    strict gesture_control check reads this as a plain fist."""
    pts = [(0.6, 0.6), (0.56, 0.52), (0.54, 0.48), (0.53, 0.45), (0.52, 0.42)]
    for y in (0.5, 0.55, 0.6, 0.65):
        pts += [(0.5, y), (0.45, y), (0.44, y + 0.01), (0.47, y + 0.01)]
    return [SimpleNamespace(x=x, y=y) for x, y in pts]


def pointing_hand(dx=0.0):
    lm = fake_hand(fist=True)
    for i, d in ((6, 0.05), (7, 0.09), (8, 0.13)):  # index straight up
        lm[i].y = 0.65 - d
    for p in lm:
        p.x += dx
    return lm


def curl_index(lm):
    """The tracker's misread: index folded back toward the palm, like a fist."""
    for i, d in ((6, 0.04), (7, 0.01), (8, -0.03)):
        lm[i].y = 0.65 - d


class HandInputTest(unittest.TestCase):
    def test_sideways_thumbs_up_fires(self):
        hand = HandInput(960, 720, hold_s=0.5)
        fired = [hand.update(sideways_thumbs_up(), 1.0, i * DT) for i in range(30)]
        self.assertIs(hand.pose, Pose.THUMBS_UP)
        self.assertIn(Pose.THUMBS_UP, fired)

    def test_other_shapes_are_not_thumbs_up(self):
        point = fake_hand()
        for i in (12, 16, 20):  # curl middle, ring, pinky: only the index stays up
            point[i].y = 0.66
        for lm in (fake_hand(), fake_hand(fist=True), point):
            self.assertFalse(is_thumbs_up(lm, 1.0))

    def test_misread_curled_finger_mid_swipe_keeps_the_line(self):
        """What the logs showed: in a fast swipe the tracker reads the pointing
        finger as curled for 1-2 frames and drops the tip onto the palm."""
        hand = HandInput(960, 720)
        ys, sheathed = [], []
        for i in range(12):
            lm = pointing_hand(dx=-0.3 + i * 0.05)
            if i in (6, 7):
                curl_index(lm)
            hand.update(lm, 1.0, i * DT)
            ys.append(hand.blade[1])
            sheathed.append(hand.sheathed)
        self.assertLess(max(ys) - min(ys), 15)  # the raw tip dropped ~100 px
        self.assertFalse(any(sheathed))

    def test_held_fist_sheathes(self):
        hand = HandInput(960, 720)
        for i in range(6):
            hand.update(fake_hand(fist=True), 1.0, i * DT)
        self.assertTrue(hand.sheathed)

    def test_hold_fires_once(self):
        hand = HandInput(960, 720, hold_s=0.5)
        fired = [hand.update(fake_hand(fist=True, thumb_up=True), 1.0, i * DT)
                 for i in range(40)]
        self.assertEqual([p for p in fired if p], [Pose.THUMBS_UP])

    def test_one_odd_frame_does_not_reset_hold(self):
        hand = HandInput(960, 720, hold_s=0.5)
        fired = []
        for i in range(40):
            lm = fake_hand(fist=True) if i == 8 else fake_hand(fist=True, thumb_up=True)
            fired.append(hand.update(lm, 1.0, i * DT))
        self.assertIn(Pose.THUMBS_UP, fired)
        self.assertLess(fired.index(Pose.THUMBS_UP), 20)

    def test_lost_hand_clears_blade(self):
        hand = HandInput(960, 720)
        hand.update(fake_hand(), 1.0, 0.0)
        self.assertIsNotNone(hand.blade)
        hand.update(None, 1.0, DT)
        self.assertIsNone(hand.blade)
        self.assertFalse(hand.trail)


if __name__ == "__main__":
    unittest.main()
