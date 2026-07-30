"""Send real keyboard and mouse events to an X display, for plugin demos.

The plugin is a native window, so demoing anything past auto-connect means
genuinely typing and clicking at it. This uses XTEST, so the events are
indistinguishable from a person at the keyboard as far as the plugin is concerned.

Only used by demo scripts — nothing in the plugin or its tests depends on it.

Usage:
    uv run --with python-xlib python3 scripts/demo_x_input.py :97 click 640 500
    uv run --with python-xlib python3 scripts/demo_x_input.py :97 type "hello world"
"""

import sys
import time

from Xlib import X, XK, display
from Xlib.ext import xtest


def _keycode(disp, char: str):
    """Keycode plus whether shift is needed, or None if we cannot type the char."""
    keysym = XK.string_to_keysym(char)

    if keysym == 0:
        special = {
            " ": "space",
            ",": "comma",
            ".": "period",
            "-": "minus",
            "_": "underscore",
            "'": "apostrophe",
            "/": "slash",
        }
        if char not in special:
            return None
        keysym = XK.string_to_keysym(special[char])

    code = disp.keysym_to_keycode(keysym)
    if code == 0:
        return None

    # Upper case and a few symbols need shift held.
    needs_shift = char.isupper() or char in '_"?:'
    return code, needs_shift


def type_text(disp, text: str, delay: float = 0.012) -> None:
    shift = disp.keysym_to_keycode(XK.string_to_keysym("Shift_L"))

    for char in text:
        entry = _keycode(disp, char)

        if entry is None:
            continue

        code, needs_shift = entry

        if needs_shift:
            xtest.fake_input(disp, X.KeyPress, shift)

        xtest.fake_input(disp, X.KeyPress, code)
        xtest.fake_input(disp, X.KeyRelease, code)

        if needs_shift:
            xtest.fake_input(disp, X.KeyRelease, shift)

        disp.sync()
        time.sleep(delay)


def click(disp, x: int, y: int) -> None:
    xtest.fake_input(disp, X.MotionNotify, x=x, y=y)
    disp.sync()
    time.sleep(0.1)
    xtest.fake_input(disp, X.ButtonPress, 1)
    xtest.fake_input(disp, X.ButtonRelease, 1)
    disp.sync()
    time.sleep(0.1)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    disp = display.Display(sys.argv[1])
    command = sys.argv[2]

    if command == "click":
        click(disp, int(sys.argv[3]), int(sys.argv[4]))
    elif command == "type":
        type_text(disp, sys.argv[3])
    else:
        print(f"unknown command: {command}")
        return 2

    disp.sync()
    return 0


if __name__ == "__main__":
    sys.exit(main())
