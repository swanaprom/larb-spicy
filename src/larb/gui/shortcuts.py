"""Ctrl+C / V / X / A / Z in text fields, whatever the keyboard language.

Tk matches Ctrl+C by the character the key types. With a Thai (or Korean, Russian, ...)
layout active that character isn't "c", so copy and paste silently do nothing. Here the
shortcut is recognized by the key itself (its key code), which doesn't change with the
layout. One table per OS: key codes differ between Windows and Linux, not between
languages.
"""

import sys
import tkinter as tk

# Windows: virtual-key codes (the same for these keys in every layout Windows offers for
# Thai, Korean, Japanese, ...; on a Latin layout they follow the printed letter).
WINDOWS_KEYS = {65: "<<SelectAll>>", 67: "<<Copy>>", 86: "<<Paste>>", 88: "<<Cut>>", 90: "<<Undo>>"}
# Linux (X11 and XWayland): hardware key codes of the A, C, V, X and Z keys.
LINUX_KEYS = {38: "<<SelectAll>>", 54: "<<Copy>>", 55: "<<Paste>>", 53: "<<Cut>>", 52: "<<Undo>>"}
# The Alt key's bit in Tk's event state. AltGr arrives as Ctrl+Alt on Windows: those keys
# type characters, so they must not become shortcuts.
_ALT_MASK = {"win32": 0x20000, "linux": 0x0008}

WIDGET_CLASSES = ("TEntry", "Entry", "Text")
# Our own binding tag, put in front of each text widget's class tag. Tk runs only the most
# specific binding per tag, and on Linux the classes bind Ctrl+A, Ctrl+K ... themselves
# (Emacs-style), which would shadow a generic Ctrl binding on the class.
TAG = "LarbShortcuts"


def action_for(platform: str, keycode: int, state: int) -> str | None:
    """The virtual event for Ctrl + this key, or None to leave the key alone.

    Args:
        platform: sys.platform ("win32", "linux", ...).
    """
    if platform.startswith("linux"):
        platform = "linux"
    table = {"win32": WINDOWS_KEYS, "linux": LINUX_KEYS}.get(platform)
    if table is None or state & _ALT_MASK[platform]:
        return None
    return table.get(keycode)


def install(root: tk.Tk) -> None:
    """Give every text field and text area under `root` the shortcuts. Call it once the
    window is built (widgets created later need attach()).

    Mac is left to Tk's own Command-key bindings (not tested here: no Mac available).
    """
    if not (sys.platform == "win32" or sys.platform.startswith("linux")):
        return

    def on_ctrl_key(event: tk.Event) -> str | None:
        action = action_for(sys.platform, event.keycode, event.state)
        if action is None:
            return None
        # Tk's own action for the shortcut, as if the English letter had been typed.
        # (Tk 8.6 text fields have no undo, so Ctrl+Z does nothing there in any language.)
        event.widget.event_generate(action)
        return "break"   # handled: don't also run Tk's own binding for the typed character

    root.bind_class(TAG, "<Control-KeyPress>", on_ctrl_key)
    _attach_all(root)


def attach(widget: tk.Misc) -> None:
    """Run the shortcuts before the widget's own class bindings."""
    tags = widget.bindtags()
    if TAG not in tags:
        widget.bindtags((TAG, *tags))


def _attach_all(widget: tk.Misc) -> None:
    for child in widget.winfo_children():
        if child.winfo_class() in WIDGET_CLASSES:
            attach(child)
        _attach_all(child)
