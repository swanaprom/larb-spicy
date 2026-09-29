"""Small widgets the window is built from: coloured buttons, fields with a placeholder,
hover hints, the sweeping download bar, and the dark dialogs."""

import tkinter as tk
from tkinter import ttk

from larb.gui import theme


class ColorButton(tk.Label):
    """A flat button in any colour, darker on hover.

    Built on a Label because a tk.Button ignores its colours on Mac. Works with the
    mouse and, when focused, with Space / Enter.

    Args:
        bg: Idle colour. Hover is a slightly darker version (GUI.md).
    """

    def __init__(self, master, text: str, command, bg: str, fg: str = theme.WHITE,
                 font=None, padx: int = 12, pady: int = 4, disabled_bg: str | None = None,
                 disabled_fg: str = theme.DISABLED_TEXT, width: int = 0) -> None:
        super().__init__(master, text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady, width=width,
                         cursor="hand2", takefocus=True, highlightthickness=1,
                         highlightbackground=theme.PANE, highlightcolor=theme.NEON)
        self._command = command
        self._bg, self._fg = bg, fg
        self._disabled_bg = disabled_bg or theme.shade(bg, 0.5)
        self._disabled_fg = disabled_fg
        self._enabled = True
        self._hover = False
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<space>", lambda _e: self.invoke())
        self.bind("<Return>", lambda _e: self.invoke())

    def style(self, text: str | None = None, bg: str | None = None, fg: str | None = None) -> None:
        """Change the label or colours (e.g. Run -> Stop)."""
        if text is not None:
            self.configure(text=text)
        if bg is not None:
            self._bg = bg
        if fg is not None:
            self._fg = fg
        self._paint()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow", takefocus=enabled)
        self._paint()

    def invoke(self) -> None:
        if self._enabled and self._command:
            self._command()

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._paint()

    def _click(self, event) -> None:
        # Only a release over the button counts, like a real button.
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def _paint(self) -> None:
        if not self._enabled:
            self.configure(bg=self._disabled_bg, fg=self._disabled_fg)
        else:
            self.configure(bg=theme.shade(self._bg, theme.HOVER) if self._hover else self._bg, fg=self._fg)


class PlaceholderEntry(ttk.Entry):
    """A text field that shows a grey hint while it's empty and not being typed in.

    Use value() / set_value(), not get(): get() would return the hint.
    """

    def __init__(self, master, placeholder: str, **kwargs) -> None:
        self._var = tk.StringVar()
        super().__init__(master, textvariable=self._var, **kwargs)
        self._placeholder = placeholder
        self._showing = False
        self.bind("<FocusIn>", self._hide, add="+")
        self.bind("<FocusOut>", self._show, add="+")
        self._show()

    def value(self) -> str:
        return "" if self._showing else self._var.get()

    def set_value(self, text: str) -> None:
        self._hide()
        self._var.set(text)
        if self.focus_get() is not self:
            self._show()

    def _show(self, _event=None) -> None:
        if not self._var.get() and self._placeholder:
            self._showing = True
            self._var.set(self._placeholder)
            self.configure(foreground=theme.MUTED)

    def _hide(self, _event=None) -> None:
        if self._showing:
            self._showing = False
            self._var.set("")
            self.configure(foreground=theme.TEXT)


class HoverHint:
    """A small box with a hint, shown after the mouse rests on a widget."""

    DELAY_MS = 500

    def __init__(self, widget: tk.Widget, text: str, wrap: int = 360) -> None:
        self._widget, self._text, self._wrap = widget, text, wrap
        self._tip: tk.Toplevel | None = None
        self._pending: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._pending = self._widget.after(self.DELAY_MS, self._show)

    def _show(self) -> None:
        self._pending = None
        x = self._widget.winfo_rootx() + 12
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tip = tk.Toplevel(self._widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(tip, text=self._text, justify="left", wraplength=self._wrap, bg=theme.FIELD,
                 fg=theme.TEXT, padx=8, pady=5, highlightthickness=1,
                 highlightbackground=theme.BORDER).pack()

    def _hide(self, _event=None) -> None:
        if self._pending:
            self._widget.after_cancel(self._pending)
            self._pending = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class SweepBar(tk.Canvas):
    """The "busy" bar of an active download: a gradient from DARK to NEON and back,
    sweeping across (GUI.md 2.3). It only shows the program is alive; the timer next
    to it shows a stuck download."""

    STEP_MS = 40
    STRIPES = 24

    def __init__(self, master, width: int = 180, height: int = 10) -> None:
        super().__init__(master, width=width, height=height, bg=theme.BAR_TROUGH, highlightthickness=0)
        self._width = width
        self._block = width // 3
        self._x = -self._block
        stripe = self._block / self.STRIPES
        for i in range(self.STRIPES):
            t = 1 - abs(2 * i / (self.STRIPES - 1) - 1)   # 0 -> 1 -> 0 across the block
            self.create_rectangle(i * stripe, 0, (i + 1) * stripe + 1, height, width=0,
                                  fill=theme.mix(theme.DARK, theme.NEON, t), tags="sweep")
        self.move("sweep", self._x, 0)
        self._job = self.after(self.STEP_MS, self._step)

    def _step(self) -> None:
        dx = max(2, self._width // 60)
        self._x += dx
        self.move("sweep", dx, 0)
        if self._x > self._width:
            self.move("sweep", -self._x - self._block, 0)
            self._x = -self._block
        self._job = self.after(self.STEP_MS, self._step)

    def destroy(self) -> None:
        self.after_cancel(self._job)
        super().destroy()


def ask(parent: tk.Misc, title: str, message: str, buttons: list[tuple[str, str]], default: str,
        colours: dict[str, str] | None = None, fonts=None, escape: str | None = None) -> str:
    """A modal dialog in the window's dark theme, with the buttons GUI.md names.

    Blocks until answered: the main window can't be used meanwhile. Enter picks the
    default, which is also the one focused; Escape and closing the dialog pick
    `escape` (by default the same: every default in GUI.md is the safe choice).

    Args:
        buttons: (answer, label) pairs, left to right.
        colours: answer -> button colour (others are grey).
        escape: The answer for Escape / closing, when it isn't `default`.

    Returns:
        The chosen answer.
    """
    colours = colours or {}
    dialog = tk.Toplevel(parent, bg=theme.PANE)
    dialog.title(title)
    dialog.transient(parent.winfo_toplevel())
    dialog.resizable(False, False)
    escape = escape or default
    answer = {"value": escape}

    def choose(value: str) -> None:
        answer["value"] = value
        dialog.destroy()

    body = tk.Frame(dialog, bg=theme.PANE, padx=20, pady=16)
    body.pack(fill="both", expand=True)
    tk.Label(body, text=message, bg=theme.PANE, fg=theme.TEXT, justify="left", wraplength=460,
             font=fonts.normal if fonts else None).pack(anchor="w")
    row = tk.Frame(body, bg=theme.PANE)
    row.pack(anchor="e", pady=(16, 0))
    focus = None
    for value, label in buttons:
        font = None if fonts is None else fonts.bold if value == default else fonts.normal
        button = ColorButton(row, label, lambda v=value: choose(v), bg=colours.get(value, theme.BUTTON), font=font)
        button.pack(side="left", padx=(8, 0))
        if value == default:
            focus = button
    # Enter needs no binding here: the focused button (the default, unless the operator
    # tabbed away) handles it itself.
    dialog.bind("<Escape>", lambda _e: choose(escape))
    dialog.protocol("WM_DELETE_WINDOW", lambda: choose(escape))

    dialog.update_idletasks()
    top = parent.winfo_toplevel()
    x = top.winfo_rootx() + (top.winfo_width() - dialog.winfo_reqwidth()) // 2
    y = top.winfo_rooty() + (top.winfo_height() - dialog.winfo_reqheight()) // 3
    dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    dialog.grab_set()
    if focus is not None:
        focus.focus_set()
    parent.wait_window(dialog)
    return answer["value"]
