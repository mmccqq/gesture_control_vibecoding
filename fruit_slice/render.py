"""Draws the game with OpenCV on top of the darkened camera image."""

import math
import random

import cv2
import numpy as np

from gesture_control.gestures import Pose

from .game import Game, Half, Item, Kind, State
from .hand import HandInput

FONT = cv2.FONT_HERSHEY_DUPLEX
AA = cv2.LINE_AA
WHITE = (255, 255, 255)
GREY = (170, 170, 170)
RED = (60, 60, 235)
GOLD = (60, 200, 255)
ICE = (255, 225, 170)
BLADE_GLOW = (255, 200, 120)

# Which held shape does something in each state.
HOLD_COMMANDS = {
    State.MENU: Pose.THUMBS_UP,
    State.OVER: Pose.THUMBS_UP,
    State.PAUSED: Pose.THUMBS_UP,
    State.PLAYING: Pose.FIST,
}

_backdrops: dict[tuple[int, int], np.ndarray] = {}


def _pt(x: float, y: float) -> tuple[int, int]:
    return int(round(x)), int(round(y))


def _mix(a, b, k: float) -> tuple[int, int, int]:
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


def _rotate(dx: float, dy: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return dx * c - dy * s, dx * s + dy * c


def text(img, s: str, org, scale: float, color, thickness: int = 2,
         center: bool = False) -> None:
    if center:
        (tw, th), _ = cv2.getTextSize(s, FONT, scale, thickness)
        org = (org[0] - tw / 2, org[1] + th / 2)
    x, y = _pt(*org)
    # Outline by offsetting: a thicker stroke would also widen the letter spacing.
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2)):
        cv2.putText(img, s, (x + dx, y + dy), FONT, scale, (20, 20, 20), thickness, AA)
    cv2.putText(img, s, (x, y), FONT, scale, color, thickness, AA)


def _backdrop(w: int, h: int) -> np.ndarray:
    """Dark vertical gradient the camera image is blended into."""
    if (w, h) not in _backdrops:
        top, bottom = np.array([40, 22, 18]), np.array([30, 18, 45])
        k = np.linspace(0, 1, h)[:, None]
        rows = (top * (1 - k) + bottom * k).astype(np.uint8)
        _backdrops[(w, h)] = np.repeat(rows[:, None, :], w, axis=1)
    return _backdrops[(w, h)]


# --- items ------------------------------------------------------------------

def draw_item(img, item: Item, now: float) -> None:
    t, x, y = item.type, item.x, item.y
    r, c = t.radius, _pt(item.x, item.y)
    if t.kind is Kind.THORN:
        for i in range(12):
            a = item.angle + i * 30
            tip, left, right = (_rotate(0, -r * 1.45, a), _rotate(-r * 0.25, -r * 0.8, a),
                                _rotate(r * 0.25, -r * 0.8, a))
            pts = np.array([_pt(x + px, y + py) for px, py in (tip, left, right)], np.int32)
            cv2.fillConvexPoly(img, pts, (95, 95, 105), AA)
        cv2.circle(img, c, int(r), t.skin, -1, AA)
        cv2.circle(img, c, int(r), (25, 25, 30), 2, AA)
        pulse = 0.5 + 0.5 * math.sin(now * 10)
        cv2.circle(img, c, int(r * 0.4), _mix((20, 20, 120), t.flesh, pulse), -1, AA)
        return

    if t.kind is Kind.FROST:
        cv2.circle(img, c, int(r * 1.35), ICE, 1, AA)
        cv2.circle(img, c, int(r), t.skin, -1, AA)
        for i in range(3):
            dx, dy = _rotate(0, r * 0.75, item.angle + i * 60)
            cv2.line(img, _pt(x - dx, y - dy), _pt(x + dx, y + dy), WHITE, 2, AA)
        cv2.circle(img, c, int(r), WHITE, 2, AA)
        return

    cv2.circle(img, c, int(r), t.skin, -1, AA)
    if t.name == "melon":
        for k in (0.3, 0.7):
            cv2.ellipse(img, c, (int(r * k), int(r) - 2), item.angle, 0, 360,
                        _mix(t.skin, (0, 0, 0), 0.4), 3, AA)
    cv2.circle(img, c, int(r), _mix(t.skin, (0, 0, 0), 0.45), 2, AA)
    if t.name != "melon":
        # Stem and leaf turn with the fruit.
        sx, sy = _rotate(0, -r * 0.85, item.angle)
        ex, ey = _rotate(0, -r * 1.15, item.angle)
        cv2.line(img, _pt(x + sx, y + sy), _pt(x + ex, y + ey), (30, 60, 90), 3, AA)
        lx, ly = _rotate(r * 0.25, -r * 1.05, item.angle)
        cv2.ellipse(img, _pt(x + lx, y + ly), (int(r * 0.28), int(r * 0.12)),
                    item.angle - 25, 0, 360, (40, 160, 60), -1, AA)
    # The highlight stays top-left: the light doesn't spin with the fruit.
    cv2.ellipse(img, _pt(x - r * 0.35, y - r * 0.38), (int(r * 0.28), int(r * 0.15)),
                -40, 0, 360, _mix(t.skin, WHITE, 0.55), -1, AA)


def draw_half(img, h: Half) -> None:
    t, r, c = h.type, h.type.radius, _pt(h.x, h.y)
    start, end = (0, 180) if h.side > 0 else (180, 360)
    cv2.ellipse(img, c, (int(r), int(r)), h.angle, start, end, t.skin, -1, AA)
    cv2.ellipse(img, c, (int(r * 0.82), int(r * 0.82)), h.angle, start, end, t.flesh, -1, AA)
    if t.name == "melon":
        for dx, dy in ((-0.4, 0.35), (0.0, 0.5), (0.4, 0.35)):
            px, py = _rotate(dx * r, dy * r * h.side, h.angle)
            cv2.ellipse(img, _pt(h.x + px, h.y + py), (4, 2), h.angle + 90, 0, 360,
                        (20, 20, 20), -1, AA)
    elif t.name in ("orange", "lime", "lemon"):
        for deg in (30, 90, 150):
            a = math.radians(deg)
            px, py = _rotate(math.cos(a) * r * 0.7, math.sin(a) * r * 0.7 * h.side, h.angle)
            cv2.line(img, c, _pt(h.x + px, h.y + py), _mix(t.flesh, WHITE, 0.5), 1, AA)


# --- HUD --------------------------------------------------------------------

def _heart(img, cx: int, cy: int, s: int, filled: bool) -> None:
    color = RED if filled else (90, 90, 90)
    thickness = -1 if filled else 2
    pts = []
    for i in range(40):
        a = i / 40 * 2 * math.pi
        hx = 16 * math.sin(a) ** 3
        hy = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
        pts.append(_pt(cx + hx * s / 16, cy - hy * s / 16))
    pts = np.array(pts, np.int32)
    if filled:
        cv2.fillPoly(img, [pts], color, AA)
    else:
        cv2.polylines(img, [pts], True, color, thickness, AA)


def draw_hud(img, game: Game, hand: HandInput, fps: float) -> None:
    h, w = img.shape[:2]
    if game.state is not State.MENU:
        text(img, str(game.score), (24, 64), 1.8, WHITE, 3)
        if game.multiplier > 1:
            (tw, _), _ = cv2.getTextSize(str(game.score), FONT, 1.8, 3)
            text(img, f"x{game.multiplier}", (40 + tw, 64), 1.0, GOLD, 2)
        text(img, f"BEST {game.best}", (26, 98), 0.65, GREY, 1)
        for i in range(game.cfg.lives):
            _heart(img, w - 40 - i * 46, 44, 18, i < game.lives)
    if game.frost_left > 0:
        frac = game.frost_left / game.cfg.frost_duration_s
        bw = 240
        x0 = (w - bw) // 2
        cv2.rectangle(img, (x0, 22), (x0 + bw, 34), (90, 70, 50), -1)
        cv2.rectangle(img, (x0, 22), (x0 + int(bw * frac), 34), ICE, -1)
        text(img, "SLOW MOTION", (w / 2, 52), 0.55, ICE, 1, center=True)

    if hand.blade is None:
        text(img, "Show your hand to the camera", (w / 2, h - 60), 0.7, GOLD, 1, center=True)
    shape = hand.pose.value.replace("_", " ") if hand.pose else "no hand"
    text(img, f"{fps:4.1f} fps   hand: {shape}   [space] start/pause  [f] fullscreen  [q] quit",
         (12, h - 14), 0.45, GREY, 1)


def draw_blade(img, hand: HandInput, sheathed: bool) -> None:
    if hand.blade is None:
        return
    if sheathed:
        cv2.circle(img, _pt(*hand.blade), 10, GREY, 2, AA)
        return
    pts = [_pt(x, y) for x, y, _ in hand.trail]
    n = len(pts)
    for glow in (True, False):
        for i in range(1, n):
            k = i / (n - 1)
            thick = max(1, int(2 + 10 * k))
            cv2.line(img, pts[i - 1], pts[i], BLADE_GLOW if glow else WHITE,
                     thick + 6 if glow else thick, AA)
    cv2.circle(img, _pt(*hand.blade), 6, WHITE, -1, AA)


def draw_hold_ring(img, game: Game, hand: HandInput) -> None:
    if (hand.blade is None or hand.hold_progress <= 0.05
            or hand.hold_pose is not HOLD_COMMANDS[game.state]):
        return
    cv2.ellipse(img, _pt(*hand.blade), (36, 36), -90, 0, 360 * hand.hold_progress,
                GOLD, 4, AA)


def draw_screens(img, game: Game) -> None:
    h, w = img.shape[:2]
    cx = w / 2
    if game.state is State.MENU:
        text(img, "ORCHARD BLADE", (cx, h * 0.26), 2.2, GOLD, 4, center=True)
        lines = [
            "Swipe your index finger fast to slice fruit",
            "Slice 3+ in one swipe for a combo bonus",
            "Avoid the thorn balls - frost berries slow time",
            "Don't let fruit fall: you have 3 lives",
            "Make a fist to sheathe the blade (hold it to pause)",
        ]
        for i, line in enumerate(lines):
            text(img, line, (cx, h * 0.40 + i * 36), 0.7, WHITE, 1, center=True)
        text(img, "Hold THUMBS UP to start", (cx, h * 0.78), 1.0, GOLD, 2, center=True)
        if game.best:
            text(img, f"Best: {game.best}", (cx, h * 0.85), 0.7, GREY, 1, center=True)
    elif game.state is State.PAUSED:
        text(img, "PAUSED", (cx, h * 0.42), 2.0, WHITE, 4, center=True)
        text(img, "Hold THUMBS UP to resume", (cx, h * 0.54), 0.9, GOLD, 2, center=True)
    elif game.state is State.OVER:
        text(img, "GAME OVER", (cx, h * 0.32), 2.2, RED, 4, center=True)
        text(img, f"Score {game.score}", (cx, h * 0.45), 1.4, WHITE, 3, center=True)
        if game.new_best:
            text(img, "NEW BEST!", (cx, h * 0.54), 1.0, GOLD, 2, center=True)
        text(img, "Hold THUMBS UP to play again", (cx, h * 0.70), 0.9, GOLD, 2, center=True)


# --- frame ------------------------------------------------------------------

def draw(frame, game: Game, hand: HandInput, now: float, fps: float) -> np.ndarray:
    w, h = game.cfg.width, game.cfg.height
    cam = cv2.resize(frame, (w, h))
    img = cv2.addWeighted(cam, 0.4, _backdrop(w, h), 0.6, 0)
    if game.frost_left > 0:
        img = cv2.addWeighted(img, 0.75, np.full_like(img, (120, 60, 20)), 0.25, 0)

    if game.splats:
        layer = img.copy()
        for s in game.splats:
            k = 1 - 0.4 * s.age / s.life
            for dx, dy, r in s.blobs:
                cv2.circle(layer, _pt(s.x + dx, s.y + dy), max(1, int(r * k)), s.color, -1, AA)
        img = cv2.addWeighted(layer, 0.45, img, 0.55, 0)

    for half in game.halves:
        draw_half(img, half)
    for item in game.items:
        draw_item(img, item, now)
    for p in game.particles:
        r = p.radius * (1 - p.age / p.life)
        if r >= 0.5:
            cv2.circle(img, _pt(p.x, p.y), max(1, int(r)), p.color, -1, AA)

    draw_blade(img, hand, sheathed=hand.sheathed)
    for pop in game.popups:
        text(img, pop.text, (pop.x, pop.y), pop.scale, pop.color, 2, center=True)

    if game.flash > 0:
        img = cv2.addWeighted(img, 1.0, np.full_like(img, RED), game.flash, 0)
    if game.shake > 0:
        amp = int(16 * game.shake / 0.35)
        img = np.roll(img, (random.randint(-amp, amp), random.randint(-amp, amp)), axis=(0, 1))

    draw_hud(img, game, hand, fps)
    draw_screens(img, game)
    draw_hold_ring(img, game, hand)
    return img
