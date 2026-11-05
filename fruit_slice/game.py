"""Game logic for Orchard Blade: fruit physics, slicing, scoring and game
states. Works in canvas pixels and knows nothing about the camera or drawing,
so it can be driven with synthetic input in tests."""

import math
import random
from dataclasses import dataclass
from enum import Enum

Point = tuple[float, float]
Color = tuple[int, int, int]  # BGR


class State(Enum):
    MENU = "menu"        # fruit flies for practice; nothing is scored
    PLAYING = "playing"
    PAUSED = "paused"
    OVER = "over"


class Kind(Enum):
    FRUIT = "fruit"  # slice it, or lose a life when it falls
    THORN = "thorn"  # don't slice it: costs a life
    FROST = "frost"  # slows time for a few seconds


@dataclass(frozen=True)
class ItemType:
    name: str
    kind: Kind
    radius: float
    skin: Color
    flesh: Color
    points: int = 1


FRUITS = (
    ItemType("apple", Kind.FRUIT, 38, (45, 40, 205), (190, 230, 245)),
    ItemType("orange", Kind.FRUIT, 40, (20, 140, 250), (70, 185, 255)),
    ItemType("lime", Kind.FRUIT, 32, (50, 195, 100), (150, 240, 190)),
    ItemType("plum", Kind.FRUIT, 30, (110, 40, 120), (80, 170, 235)),
    ItemType("lemon", Kind.FRUIT, 34, (40, 215, 245), (150, 240, 255)),
    ItemType("melon", Kind.FRUIT, 56, (45, 135, 40), (85, 75, 235), points=2),
)
THORN = ItemType("thorn", Kind.THORN, 34, (55, 50, 60), (40, 40, 220))
FROST = ItemType("frost", Kind.FROST, 30, (250, 215, 140), (255, 245, 225))


@dataclass
class GameConfig:
    width: int = 960
    height: int = 720
    gravity: float = 1100.0  # px/s^2
    lives: int = 3
    # The fingertip only cuts while moving at least this fast (px/s).
    blade_min_speed: float = 700.0
    # Items are a bit easier to hit than they look.
    hit_margin: float = 1.15
    # A stroke ends once the blade has been slower than blade_min_speed this long.
    stroke_gap_s: float = 0.15
    # Slicing this many items in one stroke earns a combo bonus.
    combo_min: int = 3
    # Seconds between volleys: starts slow and ramps to the minimum over ramp_s.
    spawn_interval_start: float = 1.6
    spawn_interval_min: float = 0.65
    ramp_s: float = 120.0
    max_volley: int = 5
    max_items: int = 12
    # No thorns at the very start, then their share grows with the difficulty.
    thorn_free_s: float = 8.0
    thorn_chance_max: float = 0.22
    frost_chance: float = 0.04
    frost_duration_s: float = 4.0
    frost_time_scale: float = 0.45
    # Every N slices in a row raises the score multiplier, up to max_multiplier.
    streak_per_multiplier: int = 8
    max_multiplier: int = 4


@dataclass
class Item:
    type: ItemType
    x: float
    y: float
    vx: float
    vy: float
    angle: float = 0.0  # degrees
    spin: float = 0.0   # degrees/s


@dataclass
class Half:
    type: ItemType
    x: float
    y: float
    vx: float
    vy: float
    angle: float  # degrees; the cut face lies along this direction
    spin: float
    side: int     # +1 or -1: which half of the disc


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    color: Color
    life: float
    age: float = 0.0


@dataclass
class Splat:
    x: float
    y: float
    color: Color
    blobs: list[tuple[float, float, float]]  # (dx, dy, radius)
    life: float = 1.6
    age: float = 0.0


@dataclass
class Popup:
    text: str
    x: float
    y: float
    color: Color
    scale: float = 1.0
    life: float = 0.9
    age: float = 0.0


def segment_hits_circle(a: Point, b: Point, c: Point, r: float) -> bool:
    dx, dy = b[0] - a[0], b[1] - a[1]
    len2 = dx * dx + dy * dy
    t = 0.0 if len2 == 0 else ((c[0] - a[0]) * dx + (c[1] - a[1]) * dy) / len2
    t = max(0.0, min(1.0, t))
    return math.hypot(c[0] - (a[0] + t * dx), c[1] - (a[1] + t * dy)) <= r


class Game:
    def __init__(self, cfg: GameConfig | None = None, best: int = 0,
                 rng: random.Random | None = None):
        self.cfg = cfg or GameConfig()
        self.rng = rng or random.Random()
        self.best = best
        self.state = State.MENU
        # Names of things that happened ("slice", "thorn", ...), for sound effects.
        # The caller drains the list.
        self.events: list[str] = []
        self._reset()

    def _reset(self) -> None:
        self.score = 0
        self.lives = self.cfg.lives
        self.streak = 0
        self.new_best = False
        self.play_time = 0.0
        self.frost_left = 0.0
        self.shake = 0.0
        self.flash = 0.0
        self.items: list[Item] = []
        self.halves: list[Half] = []
        self.particles: list[Particle] = []
        self.splats: list[Splat] = []
        self.popups: list[Popup] = []
        self._queue: list[list] = []  # [delay, Item] waiting to be launched
        self._next_spawn = 1.0
        self._blade_prev: Point | None = None
        self.blade_speed = 0.0  # px/s over the last frame
        self._stroke = 0
        self._stroke_at: Point = (0.0, 0.0)
        self._slow_for = 0.0

    @property
    def playing(self) -> bool:
        return self.state is State.PLAYING

    @property
    def multiplier(self) -> int:
        return min(self.cfg.max_multiplier, 1 + self.streak // self.cfg.streak_per_multiplier)

    @property
    def time_scale(self) -> float:
        return self.cfg.frost_time_scale if self.frost_left > 0 else 1.0

    # --- commands -----------------------------------------------------------

    def start(self) -> None:
        self._reset()
        self.state = State.PLAYING
        self.events.append("start")

    def toggle_pause(self) -> None:
        if self.state is State.PLAYING:
            self.state = State.PAUSED
        elif self.state is State.PAUSED:
            self.state = State.PLAYING
        self._blade_prev = None

    # --- per frame ----------------------------------------------------------

    def update(self, dt: float, blade: Point | None, cutting: bool = True) -> None:
        """Advance by `dt` real seconds. `blade` is the fingertip in canvas
        pixels (None when no hand is seen); `cutting` False sheathes it."""
        dt = min(dt, 0.1)  # don't let a stalled frame teleport everything
        self.shake = max(0.0, self.shake - dt)
        self.flash = max(0.0, self.flash - dt)
        if self.state is State.PAUSED:
            return
        self._update_blade(dt, blade if cutting else None)
        world_dt = dt * self.time_scale
        self._spawn(world_dt)
        self._physics(world_dt, dt)
        if self.playing:
            self.play_time += dt
            self.frost_left = max(0.0, self.frost_left - dt)

    def _update_blade(self, dt: float, blade: Point | None) -> None:
        prev, self._blade_prev = self._blade_prev, blade
        self.blade_speed = (math.dist(prev, blade) / dt
                            if blade is not None and prev is not None and dt > 0 else 0.0)
        fast = self.blade_speed >= self.cfg.blade_min_speed
        if fast:
            self._slow_for = 0.0
            for item in list(self.items):
                if segment_hits_circle(prev, blade, (item.x, item.y),
                                       item.type.radius * self.cfg.hit_margin):
                    self._slice(item, prev, blade)
        else:
            self._slow_for += dt
            if self._slow_for >= self.cfg.stroke_gap_s:
                self._end_stroke()

    def _end_stroke(self) -> None:
        n, self._stroke = self._stroke, 0
        if n >= self.cfg.combo_min and self.playing:
            self.score += n
            x, y = self._stroke_at
            self.popups.append(Popup(f"COMBO x{n}  +{n}", x, y - 40, (80, 220, 255), 1.1, 1.3))
            self.events.append("combo")

    def _slice(self, item: Item, a: Point, b: Point) -> None:
        self.items.remove(item)
        t = item.type
        if t.kind is Kind.THORN:
            self._burst(item.x, item.y, (90, 90, 100), 28, 520)
            self._burst(item.x, item.y, t.flesh, 12, 300)
            self.shake, self.flash = 0.35, 0.3
            self.events.append("thorn")
            if self.playing:
                self.popups.append(Popup("-1", item.x, item.y, (60, 60, 235), 1.3))
                self._lose_life()
            return

        angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        nx, ny = -math.sin(math.radians(angle)), math.cos(math.radians(angle))
        for side in (1, -1):
            self.halves.append(Half(
                t, item.x, item.y,
                item.vx * 0.6 + side * nx * 150, item.vy * 0.5 + side * ny * 150,
                angle, item.spin * 0.5 + side * 120, side))
        self._burst(item.x, item.y, t.flesh, 18, 380)
        self.splats.append(Splat(item.x, item.y, t.flesh, [(0.0, 0.0, t.radius * 0.6)] + [
            (self.rng.uniform(-1, 1) * t.radius, self.rng.uniform(-1, 1) * t.radius,
             t.radius * self.rng.uniform(0.15, 0.35)) for _ in range(6)]))

        if t.kind is Kind.FROST:
            self.frost_left = self.cfg.frost_duration_s
            self.popups.append(Popup("FROST!", item.x, item.y, (255, 230, 170), 1.2))
            self.events.append("frost")
        else:
            self.events.append("slice")
        if not self.playing:
            return
        self._stroke += 1
        self._stroke_at = (item.x, item.y)
        old = self.multiplier
        gained = t.points * old
        self.score += gained
        self.streak += 1
        if t.kind is Kind.FRUIT:
            self.popups.append(Popup(f"+{gained}", item.x, item.y, (255, 255, 255), 0.8, 0.6))
        if self.multiplier > old:
            self.popups.append(Popup(f"x{self.multiplier} STREAK", self.cfg.width / 2,
                                     self.cfg.height * 0.22, (60, 200, 255), 1.3, 1.2))

    def _lose_life(self) -> None:
        self.lives -= 1
        self.streak = 0
        if self.lives <= 0:
            self.state = State.OVER
            self.frost_left = 0.0
            if self.score > self.best:
                self.best = self.score
                self.new_best = True
            self.events.append("over")

    def _burst(self, x: float, y: float, color: Color, count: int, speed: float) -> None:
        for _ in range(count):
            a = self.rng.uniform(0, 2 * math.pi)
            s = speed * self.rng.uniform(0.3, 1.0)
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s,
                                           self.rng.uniform(2, 6), color,
                                           self.rng.uniform(0.4, 0.8)))

    # --- spawning -----------------------------------------------------------

    def _spawn(self, dt: float) -> None:
        for entry in self._queue:
            entry[0] -= dt
        for entry in [e for e in self._queue if e[0] <= 0]:
            self._queue.remove(entry)
            self.items.append(entry[1])

        self._next_spawn -= dt
        if self._next_spawn > 0 or self.state is State.OVER:
            return
        if self.playing:
            p = min(1.0, self.play_time / self.cfg.ramp_s)
            self._next_spawn = (self.cfg.spawn_interval_start
                                + (self.cfg.spawn_interval_min - self.cfg.spawn_interval_start) * p)
            count = self.rng.randint(1, 1 + round(p * (self.cfg.max_volley - 1)))
        else:
            p, self._next_spawn, count = 0.0, 1.3, self.rng.randint(1, 2)
        count = min(count, self.cfg.max_items - len(self.items) - len(self._queue))
        delay = 0.0
        for _ in range(count):
            self._queue.append([delay, self._new_item(p)])
            delay += self.rng.uniform(0.08, 0.25)

    def _pick_type(self, p: float) -> ItemType:
        roll = self.rng.random()
        if self.playing:
            if (self.play_time > self.cfg.thorn_free_s
                    and roll < self.cfg.thorn_chance_max * max(p, 0.25)):
                return THORN
            if self.frost_left <= 0 and roll > 1 - self.cfg.frost_chance:
                return FROST
        return self.rng.choice(FRUITS)

    def _new_item(self, p: float) -> Item:
        t = self._pick_type(p)
        w, h, g = self.cfg.width, self.cfg.height, self.cfg.gravity
        x = self.rng.uniform(0.12 * w, 0.88 * w)
        apex = self.rng.uniform(0.10 * h, 0.42 * h)
        vy = -math.sqrt(2 * g * (h + t.radius - apex))
        t_up = -vy / g
        # Drift toward the middle so things don't fly off the sides.
        target = self.rng.uniform(0.3 * w, 0.7 * w)
        vx = (target - x) / t_up * self.rng.uniform(0.4, 0.8)
        return Item(t, x, h + t.radius, vx, vy,
                    self.rng.uniform(0, 360), self.rng.uniform(-240, 240))

    # --- physics ------------------------------------------------------------

    def _physics(self, dt: float, real_dt: float) -> None:
        g, h = self.cfg.gravity, self.cfg.height
        for o in (*self.items, *self.halves):
            o.vy += g * dt
            o.x += o.vx * dt
            o.y += o.vy * dt
            o.angle += o.spin * dt

        for item in [i for i in self.items if i.vy > 0 and i.y - i.type.radius > h]:
            self.items.remove(item)
            if item.type.kind is Kind.FRUIT and self.playing:
                x = min(max(item.x, 60), self.cfg.width - 60)
                self.popups.append(Popup("MISS", x, h - 40, (60, 60, 235), 1.0))
                self.events.append("miss")
                self._lose_life()
        self.halves = [o for o in self.halves if o.y - o.type.radius <= h]

        for p in self.particles:
            p.vy += g * 0.8 * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.age += dt
        self.particles = [p for p in self.particles if p.age < p.life]
        for s in self.splats:
            s.age += real_dt
        self.splats = [s for s in self.splats if s.age < s.life]
        for pop in self.popups:
            pop.age += real_dt
            pop.y -= 40 * real_dt
        self.popups = [pop for pop in self.popups if pop.age < pop.life]
