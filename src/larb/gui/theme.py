"""Colours and fonts (docs/GUI.md "Colours"). A fixed dark theme on purpose: plain Tkinter
doesn't follow the system's light/dark setting without extra work (SPEC §6)."""

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# Accent colours, exactly as in GUI.md.
DARK = "#8B0088"
LIGHT = "#FF80FF"
NEON = "#FF00FF"
ORANGE = "#FF8800"
RED = "#FF1900"

# The standard dark greys for everything else.
BG = "#1E1E1E"          # window
PANE = "#252526"        # the three panes
FIELD = "#2D2D30"       # text fields, log
BUTTON = "#3A3A3D"      # Browse, Open file, Open folder
BORDER = "#3F3F46"
TEXT = "#E8E8E8"
INFO_TEXT = "#C8C8C8"   # INFO lines: light grey
MUTED = "#8A8A8A"       # stage names, placeholders, hints
DISABLED_TEXT = "#6A6A6A"
WHITE = "#FFFFFF"
BLACK = "#000000"
BAR_TROUGH = "#3A3A3D"

HOVER = 0.85            # hover = the idle colour, slightly darker
INACTIVE_FILTER = 0.45  # Warnings / Errors filter when not active: moved toward black


def shade(colour: str, factor: float) -> str:
    """The colour moved toward black (factor < 1)."""
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(c * factor))) for c in (r, g, b)))


def mix(a: str, b: str, t: float) -> str:
    """t = 0 gives a, t = 1 gives b."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#{:02X}{:02X}{:02X}".format(*(round(x + (y - x) * t) for x, y in zip(ca, cb)))


def _family() -> str:
    """A UI font with good Thai. Korean and Japanese come from the system's font
    fallback (Tk asks Windows / fontconfig for a font that has the character)."""
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return tkfont.nametofont("TkDefaultFont").actual("family")


class Fonts:
    def __init__(self) -> None:
        family = _family()
        self.normal = tkfont.Font(family=family, size=10)
        self.bold = tkfont.Font(family=family, size=10, weight="bold")
        self.small = tkfont.Font(family=family, size=9)
        self.run = tkfont.Font(family=family, size=13, weight="bold")
        self.log = tkfont.Font(family=family, size=10)
        self.log_bold = tkfont.Font(family=family, size=10, weight="bold")


def apply(root: tk.Tk) -> Fonts:
    """Set up the ttk styles (the 'clam' theme allows custom colours on every OS)."""
    fonts = Fonts()
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        tkfont.nametofont(name).configure(family=fonts.normal.actual("family"), size=10)
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=PANE, foreground=TEXT, fieldbackground=FIELD, bordercolor=BORDER,
                    lightcolor=PANE, darkcolor=PANE, troughcolor=BAR_TROUGH, font=fonts.normal,
                    focuscolor=NEON)
    style.configure("Pane.TFrame", background=PANE)
    style.configure("TLabel", background=PANE, foreground=TEXT)
    style.configure("Muted.TLabel", background=PANE, foreground=MUTED)
    style.configure("Progress.TLabel", background=PANE, foreground=TEXT, font=fonts.bold)
    style.configure("Stopped.TLabel", background=PANE, foreground=RED, font=fonts.bold)
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD, padding=4)
    style.map("TEntry", fieldbackground=[("disabled", PANE)], foreground=[("disabled", DISABLED_TEXT)],
              bordercolor=[("focus", NEON)], lightcolor=[("focus", NEON)])
    # 'clam' draws the circle with indicatorbackground and the dot with indicatorforeground.
    # White circles when usable, dark grey when greyed out (e.g. Mirror in Audio mode);
    # the selected dot is NEON (GUI.md).
    style.configure("TRadiobutton", background=PANE, foreground=TEXT, indicatorbackground=WHITE,
                    indicatorforeground=NEON, upperbordercolor=BORDER, lowerbordercolor=BORDER)
    style.map("TRadiobutton", indicatorbackground=[("disabled", FIELD), ("pressed", "#D8D8D8")],
              foreground=[("disabled", DISABLED_TEXT)], background=[("active", PANE)])
    style.configure("Vertical.TScrollbar", background=BUTTON, troughcolor=FIELD, bordercolor=FIELD,
                    arrowcolor=TEXT, lightcolor=BUTTON, darkcolor=BUTTON)
    style.map("Vertical.TScrollbar", background=[("active", shade(BUTTON, 1.3))])
    return fonts
