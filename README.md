# Gesture Control

Control your Mac with hand gestures through the webcam. It uses MediaPipe hand
tracking, OpenCV, and Quartz to send mouse and keyboard events.

## Setup

```sh
./setup.sh                          # venv + dependencies + hand model
.venv/bin/python -m gesture_control
```

On the first run, macOS will ask for two permissions for the app you launch it from
(Terminal, iTerm, VS Code…). Both are under **System Settings → Privacy & Security**:

- **Camera**: to see your hand
- **Accessibility**: to move the mouse and press keys

After granting a permission, restart that app.

Options: `--dry-run` (track gestures without touching mouse or keyboard), `--no-preview`,
`--camera 1`.

## Gestures

Each **hand shape** switches to a mode. Every row below can be changed in `settings.toml`.

| Hand shape | Default mode | What you do in that mode |
|---|---|---|
| 🖐 Open hand | move | Cursor follows your palm. Pinch thumb + index to click (hold to drag, pinch twice to double-click), thumb + middle to right click. Ring and pinky pinches start unassigned |
| ✌️ Two fingers (V) | scroll | Move hand up or down to scroll |
| ☝️ Point | swipe | Flick left or right to change desktop, up for Mission Control, down for the app's windows |
| ✊ Fist | freeze | Nothing happens, so you can rest your hand |
| 👍 Thumbs up | none | Unassigned |
| 🤘 Rock (index + pinky) | none | Unassigned |

**Pointing to move the cursor:** set `point = "move"` and the cursor follows your index
fingertip instead of your palm. To click, point with your thumb sticking out (like a finger
gun), then tuck the thumb against your hand (`thumb_press`). Hold it tucked to drag. Pinches
are ignored while pointing.

In the preview window, press **p** to pause and **q** to quit.

## Settings

Everything lives in **`settings.toml`**, which is created on the first run. Edit it while the
app is running: changes apply as soon as you save. If an edit is invalid, the app prints
why and keeps the previous settings. Delete the file to go back to the defaults.

```toml
[poses]
fist      = "move"               # move the cursor with a fist instead
thumbs_up = "play_pause"         # hold a shape for half a second to run an action
open_hand = "none"               # ignore a shape (the current mode continues)

[gestures]
pinch_ring  = "play_pause"
pinch_pinky = "keys:cmd+tab"       # any key combo
swipe_up    = "open:Safari"        # open an app
swipe_down  = "none"               # disable a gesture
```

The comments at the top of the file list every available action. The `[tuning]` section
adjusts sensitivity; see [gesture_control/config.py](gesture_control/config.py) for what each value does.
The most useful ones:

- `active_box`: the part of the camera image that maps to the whole screen. Shrink it to
  reach the screen edges with less arm movement.
- `filter_min_cutoff` / `filter_beta`: trade cursor smoothness against lag.
- `pinch_start` / `pinch_release`: pinch sensitivity.
- `scroll_gain`, `scroll_invert`, `swipe_min_distance`.

## Tests

```sh
.venv/bin/python -m unittest discover tests
```
