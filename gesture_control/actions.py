"""Actions a gesture can trigger. The names here are what settings.toml uses."""

from collections.abc import Callable

from .mac import KEYCODES, MEDIA_KEYS, MODIFIERS, Mac

# Called with the Mac and the current cursor position.
Action = Callable[[Mac, float, float], None]


def _key(combo: str) -> Action:
    parts = [p.strip().lower() for p in combo.split("+")]
    *mods, key = parts
    if key not in KEYCODES:
        raise ValueError(f"unknown key {key!r} in {combo!r}")
    flags = 0
    for m in mods:
        if m not in MODIFIERS:
            raise ValueError(f"unknown modifier {m!r} in {combo!r} (use {', '.join(MODIFIERS)})")
        flags |= MODIFIERS[m]
    keycode = KEYCODES[key]
    return lambda mac, x, y: mac.key(keycode, flags)


def _media(name: str) -> Action:
    code = MEDIA_KEYS[name]
    return lambda mac, x, y: mac.media_key(code)


BUILTIN: dict[str, tuple[str, Action]] = {
    "none": ("do nothing", lambda mac, x, y: None),
    "left_click": ("click (on a pinch: hold to drag)", lambda mac, x, y: mac.click(x, y)),
    "double_click": ("double click", lambda mac, x, y: mac.double_click(x, y)),
    "right_click": ("right click", lambda mac, x, y: mac.right_click(x, y)),
    "desktop_left": ("previous desktop (ctrl+left)", _key("ctrl+left")),
    "desktop_right": ("next desktop (ctrl+right)", _key("ctrl+right")),
    "mission_control": ("Mission Control (ctrl+up)", _key("ctrl+up")),
    "app_windows": ("current app's windows (ctrl+down)", _key("ctrl+down")),
    "show_desktop": ("show desktop (F11)", _key("f11")),
    "play_pause": ("play / pause media", _media("play_pause")),
    "next_track": ("next track", _media("next_track")),
    "previous_track": ("previous track", _media("previous_track")),
    "volume_up": ("volume up", _media("volume_up")),
    "volume_down": ("volume down", _media("volume_down")),
    "mute": ("mute / unmute", _media("mute")),
}


def parse_action(spec: str) -> Action:
    """Turn an action name like "right_click", "keys:cmd+shift+4" or
    "open:Safari" into a callable. Raises ValueError if it's not valid."""
    if spec in BUILTIN:
        return BUILTIN[spec][1]

    if spec.startswith("keys:"):
        return _key(spec[5:])

    if spec.startswith("open:"):
        app = spec[5:].strip()
        if not app:
            raise ValueError(f"missing app name in {spec!r}")
        return lambda mac, x, y: mac.open_app(app)

    raise ValueError(f"unknown action {spec!r}")
