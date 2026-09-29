"""What the operating system shows around the window: its identity, its icons and (on
Windows) the title bar colour. Everything here fails silently where it isn't supported:
it's cosmetic, and the window works without it."""

import sys
import tkinter as tk
from pathlib import Path

from larb.gui import theme

ASSETS = Path(__file__).resolve().parent / "assets"
ICON_TITLEBAR = ASSETS / "icon_titlebar.ico"   # white; 16/20/24/32 px: the small icon, top-left
ICON_TASKBAR = ASSETS / "icon_taskbar.ico"     # accent; 32/48/256 px: taskbar and Alt+Tab
ICON_PNG = ASSETS / "icon.png"                 # accent, 256 px: Linux (and Mac)

# Windows groups taskbar buttons by this ID. Without one of its own, the program counts as
# "Python" and the taskbar shows Python's icon instead of ours.
APP_ID = "LarbSpicy.RandomDanceCombiner"

_WM_SETICON, _ICON_SMALL, _ICON_BIG = 0x0080, 0, 1
_IMAGE_ICON, _LR_LOADFROMFILE = 1, 0x0010
_SM_CXSMICON, _SM_CXICON = 49, 11
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20      # 19 on older Windows 10 builds
_DWMWA_CAPTION_COLOR = 35                # Windows 11 only
_DWMWA_TEXT_COLOR = 36
_icons: dict[str, int] = {}              # loaded icon handles, kept for the program's lifetime
_png: tk.PhotoImage | None = None


def set_app_identity() -> None:
    """Call before the first window is created (Windows)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


def style_window(window: tk.Misc) -> None:
    """Icons and title bar for the main window or a dialog."""
    window.update_idletasks()   # the window must exist before Windows can style it
    if sys.platform == "win32":
        hwnd = int(window.wm_frame(), 16)
        _set_icons_windows(hwnd)
        _title_bar_windows(hwnd)
    else:
        _set_icon_png(window)


def _set_icons_windows(hwnd: int) -> None:
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        for which, path, metric in ((_ICON_SMALL, ICON_TITLEBAR, _SM_CXSMICON),
                                    (_ICON_BIG, ICON_TASKBAR, _SM_CXICON)):
            key = f"{path}:{which}"
            if key not in _icons:
                # Load the size Windows wants for this spot (it picks the closest in the .ico).
                size = user32.GetSystemMetrics(metric)
                _icons[key] = user32.LoadImageW(None, str(path), _IMAGE_ICON, size, size, _LR_LOADFROMFILE)
            if _icons[key]:
                user32.SendMessageW(hwnd, _WM_SETICON, which, _icons[key])
    except (AttributeError, OSError):
        pass


def _title_bar_windows(hwnd: int) -> None:
    """Windows 11: the title bar in DARK with white text. Older Windows: its dark mode, if
    it has one. Either can be refused (e.g. by an old build); then nothing changes."""
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi

        def set_attribute(attribute: int, value: int) -> bool:
            data = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)) == 0

        set_attribute(_DWMWA_USE_IMMERSIVE_DARK_MODE, 1) or set_attribute(19, 1)
        if set_attribute(_DWMWA_CAPTION_COLOR, _colorref(theme.DARK)):
            set_attribute(_DWMWA_TEXT_COLOR, _colorref(theme.WHITE))
    except (AttributeError, OSError):
        pass


def _colorref(colour: str) -> int:
    """"#RRGGBB" -> Windows' COLORREF (0x00BBGGRR)."""
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return b << 16 | g << 8 | r


def _set_icon_png(window: tk.Misc) -> None:
    global _png
    try:
        if _png is None:
            _png = tk.PhotoImage(file=str(ICON_PNG))
            window.winfo_toplevel().iconphoto(True, _png)   # True: also for dialogs opened later
    except tk.TclError:
        pass
