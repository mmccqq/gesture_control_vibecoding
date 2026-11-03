"""Load hand-shape modes, gesture->action mappings and tuning values from
settings.toml.

The file is created with defaults on first run. Edit it while the app is
running and changes apply as soon as you save."""

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .actions import BUILTIN, Action, parse_action
from .config import Config

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.toml"

# Modes a hand shape can switch to: name -> description.
MODES: dict[str, str] = {
    "move": "cursor follows your palm (your index tip for point); pinches run pinch_*",
    "scroll": "move your hand up/down to scroll",
    "swipe": "flicks run the swipe_* actions",
    "freeze": "nothing happens (rest your hand)",
}

# Hand shapes: name (matches gestures.Pose) -> (default mode or action, description).
POSES: dict[str, tuple[str, str]] = {
    "open_hand": ("move", "open hand (3+ fingers up)"),
    "two_fingers": ("scroll", "index + middle up (V)"),
    "point": ("swipe", "index finger up"),
    "fist": ("freeze", "fist"),
    "thumbs_up": ("none", "fist with thumb pointing up"),
    "rock": ("none", "index + pinky up"),
}

# Gestures you can assign an action to: name -> (default action, description).
GESTURES: dict[str, tuple[str, str]] = {
    "thumb_press": ("left_click", "move mode with point: tuck your thumb against your hand"),
    "pinch_index": ("left_click", "move mode, other shapes: pinch thumb + index"),
    "pinch_middle": ("right_click", "move mode, other shapes: pinch thumb + middle"),
    "pinch_ring": ("none", "move mode, other shapes: pinch thumb + ring"),
    "pinch_pinky": ("none", "move mode, other shapes: pinch thumb + pinky"),
    "swipe_left": ("desktop_right", "swipe mode, flick left"),
    "swipe_right": ("desktop_left", "swipe mode, flick right"),
    "swipe_up": ("mission_control", "swipe mode, flick up"),
    "swipe_down": ("app_windows", "swipe mode, flick down"),
}

# Tuning keys that only take effect after a restart.
RESTART_KEYS = {"camera_index", "frame_width", "frame_height"}


class SettingsError(ValueError):
    pass


@dataclass
class Settings:
    config: Config = field(default_factory=Config)
    poses: dict[str, str] = field(
        default_factory=lambda: {p: default for p, (default, _) in POSES.items()})
    gestures: dict[str, str] = field(
        default_factory=lambda: {g: default for g, (default, _) in GESTURES.items()})
    # Parsed actions for every gesture, and for poses mapped to an action.
    actions: dict[str, Action] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.actions:
            self.actions = {g: parse_action(spec) for g, spec in self.gestures.items()}
            self.actions |= {p: parse_action(spec) for p, spec in self.poses.items()
                             if spec not in MODES}


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (tuple, list)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, str):
        return f'"{v}"'
    return repr(v)


def default_toml() -> str:
    lines = [
        "# Gesture Control settings. Changes apply as soon as you save",
        "# (except camera_index / frame_width / frame_height, which need a restart).",
        "#",
        "# [poses] sets what each hand shape does. Either a mode:",
    ]
    lines += [f"#   {name:<16}{desc}" for name, desc in MODES.items()]
    lines += [
        "# or any action below, which runs once when you hold the shape",
        "# (for pose_action_hold_s). \"none\" ignores the shape: the current mode continues.",
        "#",
        "# [gestures] sets the action for each pinch/thumb press (in move mode) and flick",
        "# (in swipe mode).",
        "#",
        "# Available actions:",
    ]
    lines += [f"#   {name:<16}{desc}" for name, (desc, _) in BUILTIN.items()]
    lines += [
        '#   keys:<combo>    press a key combo, e.g. "keys:cmd+shift+4", "keys:cmd+tab"',
        "#                   modifiers: cmd shift ctrl alt fn; keys: a-z 0-9 f1-f12",
        "#                   left right up down space return tab escape delete ...",
        '#   open:<App>      open an app, e.g. "open:Safari"',
        "",
        "[poses]",
    ]
    for name, (default, desc) in POSES.items():
        lines += [f"# {desc}", f'{name} = "{default}"']
    lines += [
        "",
        "[gestures]",
    ]
    for name, (default, desc) in GESTURES.items():
        lines += [f"# {desc}", f'{name} = "{default}"']
    lines += [
        "",
        "[tuning]",
        "# See gesture_control/config.py for what each value does.",
    ]
    lines += [f"{f.name} = {_toml_value(getattr(Config(), f.name))}" for f in fields(Config)]
    return "\n".join(lines) + "\n"


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    """Read settings, creating the file with defaults if it doesn't exist.
    Raises SettingsError with a readable message if anything is invalid."""
    if not path.exists():
        path.write_text(default_toml())
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise SettingsError(f"{path.name}: {e}") from None

    unknown_sections = set(data) - {"poses", "gestures", "tuning"}
    if unknown_sections:
        raise SettingsError(f"{path.name}: unknown section(s) {sorted(unknown_sections)}")

    settings = Settings()

    for name, spec in data.get("poses", {}).items():
        if name not in POSES:
            raise SettingsError(f"{path.name}: unknown hand shape {name!r} "
                                f"(choose from {', '.join(POSES)})")
        if not isinstance(spec, str):
            raise SettingsError(f"{path.name}: {name} must be a string, like \"scroll\"")
        settings.actions.pop(name, None)
        if spec not in MODES:
            try:
                settings.actions[name] = parse_action(spec)
            except ValueError as e:
                raise SettingsError(f"{path.name}: {name}: {e} "
                                    f"(modes: {', '.join(MODES)})") from None
        settings.poses[name] = spec

    for name, spec in data.get("gestures", {}).items():
        if name not in GESTURES:
            raise SettingsError(f"{path.name}: unknown gesture {name!r} "
                                f"(choose from {', '.join(GESTURES)})")
        if not isinstance(spec, str):
            raise SettingsError(f"{path.name}: {name} must be a string, like \"right_click\"")
        try:
            settings.actions[name] = parse_action(spec)
        except ValueError as e:
            raise SettingsError(f"{path.name}: {name}: {e}") from None
        settings.gestures[name] = spec

    types = {f.name: type(getattr(settings.config, f.name)) for f in fields(Config)}
    for key, value in data.get("tuning", {}).items():
        if key not in types:
            raise SettingsError(f"{path.name}: unknown tuning key {key!r}")
        want = types[key]
        if want is tuple:
            if not (isinstance(value, list) and len(value) == 4):
                raise SettingsError(f"{path.name}: {key} must be a list of 4 numbers")
            value = tuple(float(v) for v in value)
        elif want is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        elif not isinstance(value, want) or (want is int and isinstance(value, bool)):
            raise SettingsError(f"{path.name}: {key} must be {want.__name__}")
        setattr(settings.config, key, value)

    return settings


class SettingsWatcher:
    """Reloads settings when the file's modification time changes."""

    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path
        self.settings = load_settings(path)
        self._mtime = path.stat().st_mtime

    def poll(self) -> Settings | None:
        """Return new settings if the file changed and is valid, else None.
        Invalid edits are reported and the previous settings stay active."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return None
        if mtime == self._mtime:
            return None
        self._mtime = mtime
        try:
            new = load_settings(self.path)
        except SettingsError as e:
            print(f"Settings not applied: {e}")
            return None
        restart = [k for k in RESTART_KEYS
                   if getattr(new.config, k) != getattr(self.settings.config, k)]
        if restart:
            print(f"Note: changes to {', '.join(restart)} apply after a restart.")
        self.settings = new
        print("Settings reloaded.")
        return new
