"""The operator window. Started by `python -m larb` with no arguments (run.bat / run.sh
without arguments). Design: docs/GUI.md.

Developer switch: LARB_GUI_MAC=1 lays the bottom row out as on a Mac (mirrored), so
it can be checked on Windows and Linux. Not for operators.
"""

import os
import sys


def main() -> int:
    import tkinter as tk

    from larb import app
    from larb.core.errors import LarbError
    from larb.gui.widgets import ask
    from larb.gui.window import Window

    if sys.platform == "win32":
        # Sharp text on scaled displays (125 %, 150 %): without this Windows stretches a
        # blurry bitmap of the window.
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass

    root = tk.Tk()
    store = app.settings_store()
    try:
        settings = store.load()   # read once, when the window opens (SPEC §7)
    except LarbError as e:
        root.withdraw()
        ask(root, "Settings", f"The settings can't be loaded:\n\n{e}", [("ok", "OK")], default="ok")
        root.destroy()
        return 1
    mac = sys.platform == "darwin" or os.environ.get("LARB_GUI_MAC") == "1"
    Window(root, store, settings, mac)
    _dark_title_bar(root)
    root.mainloop()
    return 0


def _dark_title_bar(root) -> None:
    """Windows 10/11 draw the title bar in the system's light colours unless asked;
    the rest of the window is dark (fixed theme). Elsewhere, nothing to do."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on older Windows 10 builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                                         ctypes.sizeof(value)) == 0:
                break
    except (AttributeError, OSError):
        pass
