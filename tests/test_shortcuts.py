"""Ctrl+C / V / X / A / Z by the key, not the typed character (slice 5): they must work
with a Thai, Korean or Japanese keyboard layout active, and still work in English."""

import sys
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fakes  # noqa: E402,F401  (puts src/ on the path)
from larb.gui import shortcuts  # noqa: E402
from larb.gui.shortcuts import LINUX_KEYS, WINDOWS_KEYS, action_for  # noqa: E402

# (keysym the layout types, Windows key code, Linux key code). With a Thai layout the C key
# types แ, V types อ, A types ฟ: anything but c / v / a. Tk can only generate keysyms the
# active layout has (on an English system: no Thai ones), so another letter stands in for
# the Thai character: what matters is that the typed character isn't the shortcut's letter.
OTHER_C = ("k", 67, 54)
OTHER_V = ("k", 86, 55)
OTHER_A = ("k", 65, 38)
ENGLISH_V = ("v", 86, 55)
PLAIN_K = ("k", 75, 45)


class ActionTest(unittest.TestCase):
    def test_same_key_codes_whatever_the_language(self):
        self.assertEqual(action_for("win32", 67, 0), "<<Copy>>")
        self.assertEqual(action_for("linux", 55, 0), "<<Paste>>")
        self.assertEqual({action_for("win32", k, 0) for k in WINDOWS_KEYS},
                         {"<<SelectAll>>", "<<Copy>>", "<<Paste>>", "<<Cut>>", "<<Undo>>"})
        self.assertEqual({action_for("linux", k, 0) for k in LINUX_KEYS},
                         {action_for("win32", k, 0) for k in WINDOWS_KEYS})

    def test_other_keys_and_altgr_are_left_alone(self):
        self.assertIsNone(action_for("win32", 66, 0))              # Ctrl+B
        self.assertIsNone(action_for("win32", 67, 0x20000))        # AltGr+C types a character
        self.assertIsNone(action_for("linux", 54, 0x0008))         # Alt held
        self.assertIsNone(action_for("darwin", 8, 0))              # Mac: Tk's own bindings

    def test_numlock_doesnt_matter_on_windows(self):
        self.assertEqual(action_for("win32", 86, 0x0008), "<<Paste>>")   # 0x0008 is NumLock there


@unittest.skipUnless(sys.platform == "win32" or sys.platform.startswith("linux"), "Windows / Linux only")
class InWidgetTest(unittest.TestCase):
    """Real Tk events, as a keyboard in another language sends them."""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        self.addCleanup(self.root.destroy)
        # Key events go to the focused widget, and a hidden window can't have focus: so a
        # real window, placed off the screen.
        self.root.geometry("200x80+-3000+-3000")
        self.entry = ttk.Entry(self.root)
        self.entry.pack()
        shortcuts.install(self.root)   # after the widgets exist, as the window does
        self.root.update()

    def press(self, key):
        keysym, windows_code, linux_code = key
        self.entry.focus_force()
        self.root.update()
        code = windows_code if sys.platform == "win32" else linux_code
        self.entry.event_generate("<Control-KeyPress>", keysym=keysym, keycode=code, when="now")
        self.root.update()

    def test_other_layout_copy_and_paste(self):
        self.entry.insert(0, "เพลง Drama")
        self.entry.selection_range(0, "end")
        self.root.clipboard_clear()
        self.press(OTHER_C)
        self.assertEqual(self.root.clipboard_get(), "เพลง Drama")
        self.entry.delete(0, "end")
        self.press(OTHER_V)
        self.assertEqual(self.entry.get(), "เพลง Drama")

    def test_select_all(self):
        self.entry.insert(0, "https://sheet")
        self.press(OTHER_A)
        self.assertEqual(self.entry.selection_get(), "https://sheet")

    def test_english_pastes_once(self):
        self.root.clipboard_clear()
        self.root.clipboard_append("x")
        self.press(ENGLISH_V)
        self.assertEqual(self.entry.get(), "x")   # not "xx": Tk's own binding doesn't also run

    def test_other_ctrl_keys_do_nothing(self):
        self.root.clipboard_clear()
        self.root.clipboard_append("x")
        self.press(PLAIN_K)
        self.assertEqual(self.entry.get(), "")

    def test_text_area_select_all_and_copy(self):
        text = tk.Text(self.root)
        text.pack()
        shortcuts.attach(text)         # created after install()
        text.insert("1.0", "row 3: ok: Drama - เอสป้า")
        text.configure(state="disabled")   # like the log panel
        self.root.update()
        text.focus_force()
        self.root.update()
        code = {"win32": (65, 67)}.get(sys.platform, (38, 54))
        text.event_generate("<Control-KeyPress>", keysym="k", keycode=code[0], when="now")
        text.event_generate("<Control-KeyPress>", keysym="k", keycode=code[1], when="now")
        self.root.update()
        # Tk's own select-all in a text area includes its final line break.
        self.assertEqual(self.root.clipboard_get().rstrip("\n"), "row 3: ok: Drama - เอสป้า")


if __name__ == "__main__":
    unittest.main()
