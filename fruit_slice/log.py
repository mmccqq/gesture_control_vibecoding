"""Session logs: each run writes a pair of files to fruit_slice/logs/.

  <date_time>.log  readable: settings, game events (slices, misses, combos, game
                   over...) and a performance line every few seconds
  <date_time>.csv  one row per camera frame: the fingertip as tracked, the
                   smoothed blade (estimated=1 when placed from the knuckle
                   because the finger was misread), blade speed, hand shape and
                   game state, to see exactly what the blade did during a swipe

Only the newest KEEP_SESSIONS runs are kept."""

import csv
import logging
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
KEEP_SESSIONS = 20
STATS_EVERY_S = 5.0
CSV_FIELDS = ["t", "dt_ms", "state", "pose", "raw_x", "raw_y", "blade_x", "blade_y",
              "estimated", "speed", "cutting", "items", "score", "lives"]


def _num(v: float | None) -> str:
    return "" if v is None else f"{v:.1f}"


class GameLog:
    def __init__(self, log_dir: Path = LOG_DIR, keep: int = KEEP_SESSIONS):
        log_dir.mkdir(parents=True, exist_ok=True)
        self._prune(log_dir, keep - 1)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.path = log_dir / f"{stamp}.log"
        self.csv_path = log_dir / f"{stamp}.csv"

        self._logger = logging.getLogger(f"fruit_slice.{stamp}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._handler = logging.FileHandler(self.path)
        self._handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d  %(message)s",
                                                     "%H:%M:%S"))
        self._logger.addHandler(self._handler)

        self._csv_file = open(self.csv_path, "w", newline="")
        self._csv = csv.writer(self._csv_file)
        self._csv.writerow(CSV_FIELDS)
        self._t0: float | None = None
        self._stats_start = 0.0
        self._frames = self._hand_frames = 0
        self._slowest = 0.0

    @staticmethod
    def _prune(log_dir: Path, keep: int) -> None:
        logs = sorted(log_dir.glob("*.log"))  # names start with the date, so oldest first
        for log in logs[:max(0, len(logs) - keep)]:
            log.unlink(missing_ok=True)
            log.with_suffix(".csv").unlink(missing_ok=True)

    def info(self, message: str) -> None:
        self._logger.info(message)

    def frame(self, now: float, dt: float, game, hand, cutting: bool) -> None:
        if self._t0 is None:
            self._t0 = self._stats_start = now
        raw = hand.raw or (None, None)
        blade = hand.blade or (None, None)
        self._csv.writerow([
            f"{now - self._t0:.3f}", f"{dt * 1000:.1f}", game.state.value,
            hand.pose.value if hand.pose else "",
            _num(raw[0]), _num(raw[1]), _num(blade[0]), _num(blade[1]), int(hand.estimated),
            f"{game.blade_speed:.0f}",
            int(cutting and game.blade_speed >= game.cfg.blade_min_speed),
            len(game.items), game.score, game.lives,
        ])

        self._frames += 1
        self._hand_frames += hand.blade is not None
        self._slowest = max(self._slowest, dt)
        if now - self._stats_start >= STATS_EVERY_S:
            fps = self._frames / (now - self._stats_start)
            self.info(f"perf: {fps:.1f} fps, slowest frame {self._slowest * 1000:.0f} ms, "
                      f"hand seen in {100 * self._hand_frames / self._frames:.0f}% of frames")
            self._csv_file.flush()
            self._stats_start, self._frames, self._hand_frames, self._slowest = now, 0, 0, 0.0

    def close(self) -> None:
        self._csv_file.close()
        self._logger.removeHandler(self._handler)
        self._handler.close()
