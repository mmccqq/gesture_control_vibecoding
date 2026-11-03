# Orchard Blade

A fruit-slicing game played with your index finger through the webcam. It reuses the
gesture control program's hand tracking (`gesture_control.tracker`), smoothing filter
(`gesture_control.filters`) and hand-shape detection (`gesture_control.gestures`).

## Run

From the project root (after `./setup.sh`):

```sh
.venv/bin/python -m fruit_slice              # options: --camera 1  --mute  --fullscreen  --no-log
```

Only **Camera** permission is needed: the game doesn't move the mouse or press keys.

## How to play

| Do this | What happens |
|---|---|
| ☝️ Swipe your index finger **fast** | The blade cuts. Slow movement doesn't cut, so you can aim |
| 👍 Hold a thumbs up (~1 s) | Start, resume, or play again |
| ✊ Make a fist | Sheathes the blade (no cutting). Hold it to pause |

- Each fruit is worth 1 point (watermelon is worth 2). If a fruit falls off the bottom, you lose a life. You have 3 lives.
- Slice **3 or more in one swipe** for a combo bonus.
- Every 8 slices in a row raises your score multiplier, up to x4. A miss or a thorn resets it.
- **Thorn balls** (spiky, red core): slicing one costs a life.
- **Frost berries** (icy blue): slicing one slows time for 4 seconds.
- The game speeds up and throws more thorns over the first two minutes.
- On the title screen you can slice fruit for practice. Nothing is scored there.

Keyboard: **space** start/pause, **f** fullscreen, **q** / **esc** quit.

The bottom line of the window shows the hand shape the camera sees (`hand: thumbs up`).
If thumbs up doesn't register, raise your thumb clearly above your fist and keep the hand
still until the gold ring around your fingertip closes. Space always works as a fallback.
Your best score is saved in `fruit_slice/best_score.txt`.

## Logs

Every run writes two files to `fruit_slice/logs/`, named by date and time. Only the
last 20 runs are kept.

- **`.log`**: what happened, with timestamps. It records the settings, starts and
  pauses, each slice (fruit, points and blade speed), misses, thorns, combos and game
  over. Every 5 seconds it also writes a performance line (fps, slowest frame, how
  often the hand was seen).
- **`.csv`**: one row per camera frame. Each row has the fingertip position straight
  from the tracker (`raw_x/raw_y`), the smoothed blade position (`blade_x/blade_y`),
  the blade speed in px/s, whether it was cutting, the hand shape, and the
  score/lives. `estimated=1` marks frames where motion blur made the tracker misread
  your finger as curled, so the blade was placed from your knuckle instead. Use it to check what the blade actually did during a swipe.

## Files

- [game.py](game.py): physics, slicing, scoring, game states. Tunables are in `GameConfig`
- [camera.py](camera.py): camera + hand tracking on a background thread, so the game keeps the camera's 30 fps
- [hand.py](hand.py): fingertip → blade position (smoothed by `PointFilter`) and trail, plus held-shape commands
- [log.py](log.py): the session logs above
- [render.py](render.py): OpenCV drawing on top of the dimmed camera image
- [sound.py](sound.py): sound effects from the macOS system sounds (`afplay`)

## Tests

```sh
.venv/bin/python -m unittest discover -s fruit_slice/tests -t .
```
