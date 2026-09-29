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
    from larb.gui import system
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
    system.set_app_identity()   # before the first window: the taskbar shows our icon, not Python's

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
    root.mainloop()
    return 0
