"""The operator window (docs/GUI.md). Draws and wires widgets; the decisions live in
state.py, the run happens in runner.py, and the core does the work.

The window reads the settings once when it opens and saves them when Run is pressed
(SPEC §7). The Sheet and Countdown fields are remembered the same way, in their own
file (memory.py). It never calls yt-dlp or FFmpeg (SPEC §5).
"""

import queue
import sys
import time
import tkinter as tk
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

from larb import app
from larb.adapters.toml_settings import TomlSettingsStore
from larb.core.cache import cache_summary, clear_cache
from larb.core.errors import LarbError, StoppedError
from larb.core.models import Level, LogEvent, Settings
from larb.core.settings import correct_crossfade, ensure_folder, validate_settings
from larb.gui import shortcuts, system, theme
from larb.gui.memory import LastInputs, load_last_inputs, save_last_inputs
from larb.gui.opening import OpenAttempt, start_open
from larb.gui.runner import Done, EstimateWorker, RunWorker, cache_folder
from larb.gui.state import (ActiveDownloads, Fields, LogCounts, LogFilter, Phase, ProgressView,
                            bottom_row, clear_cache_question, controls, estimate_log_line, estimate_message,
                            log_line, open_failure_message, run_request, settings_from_fields, shown_folder,
                            shown_in_log, visible)
from larb.gui.widgets import ColorButton, HoverHint, OverallBar, PlaceholderEntry, SweepBar, ask

TITLE = "LARB - Spicy"
POLL_MS = 100           # how often the window takes new events from the run
TICK_MS = 1000          # how often the download timers move
MAX_EVENTS_PER_POLL = 500   # keeps the window responsive when a burst of events arrives
OPEN_POLL_MS = 200      # how often an Open file / Open folder click is checked for failure
LABEL_CHARS = 48        # active download titles are cut to this
MIRROR_HINT = ("Everything: every song ends up mirrored; rows already marked in the sheet's "
               "Mirrored column are not flipped twice. Ignore: nothing is flipped.")
EST_LENGTH_HINT = ("How long the output would be, without downloading any song. Songs already "
                   "downloaded for this mode are measured; the others count by their time range.")
VIDEO_TYPES = [("Video or audio", "*.mp4 *.mkv *.webm *.mov *.mp3 *.m4a *.wav"), ("All files", "*.*")]
CSV_TYPES = [("CSV files", "*.csv"), ("All files", "*.*")]


class Window:
    """Args:
        store: The loaded settings store; `settings` is what it loaded.
        mac: Lay the bottom row out as on a Mac (mirrored).
        inputs_file: Where the Sheet and Countdown fields are remembered.
            Default: app.LAST_INPUTS_FILE.
    """

    def __init__(self, root: tk.Tk, store: TomlSettingsStore, settings: Settings, mac: bool,
                 inputs_file: Path | None = None) -> None:
        self.root = root
        self.store = store
        self.settings = settings        # as last loaded or saved
        self.mac = mac
        self.inputs_file = inputs_file or app.LAST_INPUTS_FILE
        self.fonts = theme.apply(root)
        self.phase = Phase.IDLE
        self.worker: RunWorker | EstimateWorker | None = None
        # What an estimate puts back when it ends: it doesn't change what the last run left.
        self.phase_before_estimate = Phase.IDLE
        self.progress_before_estimate = ProgressView()
        self.closing = False            # close the window once the run has stopped
        self.output_path: Path | None = None
        self.progress = ProgressView()
        self.counts = LogCounts()
        self.downloads = ActiveDownloads()
        self.log_filter = LogFilter.ALL
        self.download_rows: dict[str, tuple[tk.Frame, tk.Label, SweepBar, tk.Label]] = {}

        root.title(TITLE)
        outer = tk.Frame(root, bg=theme.BG, padx=10, pady=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)          # only the middle pane grows (its log panel)
        self._build_top(outer).grid(row=0, column=0, sticky="nsew")
        self._build_middle(outer).grid(row=1, column=0, sticky="nsew", pady=8)
        self._build_bottom(outer).grid(row=2, column=0, sticky="nsew")

        self._load_fields(settings)
        remembered = load_last_inputs(self.inputs_file)
        self.sheet.set_value(remembered.sheet)
        self.countdown.set_value(remembered.countdown)
        self.sheet.on_change(self._apply_controls)   # Est. Length needs a sheet
        self._apply_controls()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        shortcuts.install(root)

        # A fixed minimum size: below it nothing shrinks further (GUI.md).
        root.update_idletasks()
        root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())
        root.geometry(f"{max(root.winfo_reqwidth(), 900)}x{max(root.winfo_reqheight(), 720)}")
        system.style_window(root)

    # -- building ------------------------------------------------------------------

    @staticmethod
    def _pane(master) -> ttk.Frame:
        # No pane titles: the three panes speak for themselves (maintainer decision).
        # Grid row 0 is left empty, so the rows below keep their numbers.
        return ttk.Frame(master, style="Pane.TFrame", padding=(12, 10, 12, 10))

    def _browse_button(self, master, command) -> ColorButton:
        return ColorButton(master, "Browse", command, bg=theme.BUTTON, font=self.fonts.normal, pady=3)

    def _build_top(self, master) -> ttk.Frame:
        pane = self._pane(master)
        pane.columnconfigure(1, weight=1)
        pad = {"pady": 3}

        def label(row: int, text: str) -> ttk.Label:
            widget = ttk.Label(pane, text=text)
            widget.grid(row=row, column=0, sticky="w", padx=(0, 12), **pad)
            return widget

        label(1, "Sheet")
        self.sheet = PlaceholderEntry(pane, "Google Sheet link / Path to CSV file")
        self.sheet.grid(row=1, column=1, sticky="ew", **pad)
        self.sheet_browse = self._browse_button(pane, self._browse_sheet)
        self.sheet_browse.grid(row=1, column=2, sticky="ew", padx=(8, 0), **pad)

        label(2, "Rows")
        rows = ttk.Frame(pane, style="Pane.TFrame")
        rows.grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(rows, text="from").pack(side="left")
        self.rows_from = ttk.Entry(rows, width=7)
        self.rows_from.pack(side="left", padx=(6, 12))
        ttk.Label(rows, text="to").pack(side="left")
        self.rows_to = ttk.Entry(rows, width=7)
        self.rows_to.pack(side="left", padx=(6, 12))
        ttk.Label(rows, text="(empty = first / last row)", style="Muted.TLabel").pack(side="left")

        label(3, "Output")
        choices = ttk.Frame(pane, style="Pane.TFrame")
        choices.grid(row=3, column=1, columnspan=2, sticky="w", **pad)
        self.output_var = tk.StringVar(value="audio")
        self.output_radios = [ttk.Radiobutton(choices, text=text, value=value, variable=self.output_var,
                                              command=self._apply_controls)
                              for text, value in (("Video", "video"), ("Audio", "audio"))]
        for radio in self.output_radios:
            radio.pack(side="left", padx=(0, 10))
        mirror_label = ttk.Label(choices, text="Mirror")
        mirror_label.pack(side="left", padx=(30, 10))
        self.mirror_var = tk.StringVar(value="ignore")
        self.mirror_radios = [ttk.Radiobutton(choices, text=text, value=value, variable=self.mirror_var)
                              for text, value in (("Everything", "everything"), ("Ignore", "ignore"))]
        for radio in self.mirror_radios:
            radio.pack(side="left", padx=(0, 10))
        for widget in (mirror_label, *self.mirror_radios):
            HoverHint(widget, MIRROR_HINT)

        label(4, "Countdown")
        self.countdown = PlaceholderEntry(pane, "(default countdown)")
        self.countdown.grid(row=4, column=1, sticky="ew", **pad)
        self.countdown_browse = self._browse_button(pane, self._browse_countdown)
        self.countdown_browse.grid(row=4, column=2, sticky="ew", padx=(8, 0), **pad)

        label(5, "Crossfade")
        fade = ttk.Frame(pane, style="Pane.TFrame")
        fade.grid(row=5, column=1, sticky="w", **pad)
        self.crossfade = ttk.Entry(fade, width=7)
        self.crossfade.pack(side="left")
        ttk.Label(fade, text="s").pack(side="left", padx=(6, 0))
        for sequence in ("<FocusOut>", "<Return>"):
            self.crossfade.bind(sequence, lambda _e: self._fix_crossfade())

        label(6, "Save to")
        self.output_dir = ttk.Entry(pane)
        self.output_dir.grid(row=6, column=1, sticky="ew", **pad)
        for sequence in ("<FocusOut>", "<Return>"):
            self.output_dir.bind(sequence, lambda _e: self._fix_output_dir())
        self.output_browse = self._browse_button(pane, self._browse_output)
        self.output_browse.grid(row=6, column=2, sticky="ew", padx=(8, 0), **pad)

        self.inputs = [self.sheet, self.rows_from, self.rows_to, *self.output_radios, self.countdown,
                       self.crossfade, self.output_dir]
        self.input_buttons = [self.sheet_browse, self.countdown_browse, self.output_browse]
        return pane

    def _build_middle(self, master) -> ttk.Frame:
        pane = self._pane(master)
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(2, weight=1)

        filters = ttk.Frame(pane, style="Pane.TFrame")
        filters.grid(row=1, column=0, sticky="w", pady=(0, 6))
        self.filter_buttons = {}
        for log_filter in LogFilter:
            button = ColorButton(filters, "", lambda f=log_filter: self._set_filter(f), bg=theme.BUTTON,
                                 font=self.fonts.small, padx=10, pady=2)
            button.pack(side="left", padx=(0, 6))
            self.filter_buttons[log_filter] = button
        self._paint_filters()

        box = tk.Frame(pane, bg=theme.FIELD, highlightthickness=1, highlightbackground=theme.BORDER)
        box.grid(row=2, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        measure = self.fonts.log.measure
        stops = [measure("00:00:00") + 12]
        stops.append(stops[-1] + measure("WARNING") + 12)
        stops.append(stops[-1] + measure("countdown") + 12)
        self.log = tk.Text(box, height=14, wrap="word", bg=theme.FIELD, fg=theme.INFO_TEXT, bd=0,
                           padx=8, pady=6, font=self.fonts.log, insertbackground=theme.TEXT,
                           selectbackground=theme.DARK, tabs=stops, cursor="arrow")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set, state="disabled")
        self.log.tag_configure("muted", foreground=theme.MUTED)
        self.log.tag_configure("INFO", foreground=theme.INFO_TEXT)
        self.log.tag_configure("WARNING", foreground=theme.ORANGE)
        self.log.tag_configure("ERROR", foreground=theme.RED, font=self.fonts.log_bold)
        # Wrapped lines continue under the message, not under the time.
        self.log.configure(spacing1=1, spacing3=1)
        self.log.tag_configure("line", lmargin2=stops[-1] + 8)

        progress = ttk.Frame(pane, style="Pane.TFrame")
        progress.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        progress.columnconfigure(1, weight=1)
        self.progress_label = ttk.Label(progress, text="", style="Progress.TLabel", width=26)
        self.progress_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.progress_bar = OverallBar(progress)
        self.progress_bar.grid(row=0, column=1, sticky="ew")

        # Room for the active downloads is kept even when there are none, so the log
        # panel doesn't jump when they appear.
        self.downloads_box = ttk.Frame(pane, style="Pane.TFrame")
        self.downloads_box.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        self.downloads_box.columnconfigure(0, weight=1)
        row_height = self.fonts.normal.metrics("linespace") + 8
        for i in range(max(self.settings.download.max_parallel_downloads, 1)):
            self.downloads_box.rowconfigure(i, minsize=row_height)

        opens = ttk.Frame(pane, style="Pane.TFrame")
        opens.grid(row=5, column=0, sticky="e", pady=(6, 0))
        self.open_file = ColorButton(opens, "Open file", self._open_file, bg=theme.BUTTON,
                                     font=self.fonts.normal, pady=3)
        self.open_file.pack(side="left", padx=(0, 6))
        self.open_folder = ColorButton(opens, "Open folder", self._open_folder, bg=theme.BUTTON,
                                       font=self.fonts.normal, pady=3)
        self.open_folder.pack(side="left")
        self._show_progress(False)
        return pane

    def _build_bottom(self, master) -> ttk.Frame:
        pane = ttk.Frame(master, style="Pane.TFrame", padding=(12, 10))
        self.run_button = ColorButton(pane, "RUN", self._on_run_button, bg=theme.NEON, fg=theme.WHITE,
                                      font=self.fonts.run, padx=36, pady=8, width=8)   # RUN and STOP same size
        self.est_length = ColorButton(pane, "Est. Length", self._start_estimate, bg=theme.LIGHT,
                                      fg=theme.BLACK, font=self.fonts.normal, pady=6,
                                      disabled_bg=theme.mix(theme.LIGHT, theme.PANE, 0.6),
                                      disabled_fg="#4A4A4A")
        HoverHint(self.est_length, EST_LENGTH_HINT)
        self.clear_cache_button = ColorButton(pane, "Clear cache", self._clear_cache, bg=theme.LIGHT,
                                              fg=theme.BLACK, font=self.fonts.normal, pady=6)
        widgets = {"run": self.run_button, "est_length": self.est_length,
                   "clear_cache": self.clear_cache_button}
        order = bottom_row(self.mac)
        # The gap sits between Run and the other two, wherever Run is.
        gap = order.index("run") + 1 if order[0] == "run" else order.index("run")
        column = 0
        for i, name in enumerate(order):
            if i == gap:
                pane.columnconfigure(column, weight=1)
                column += 1
            widgets[name].grid(row=0, column=column, padx=(0 if column == 0 else 8, 0), sticky="ns")
            column += 1
        return pane

    # -- fields ----------------------------------------------------------------------

    def _load_fields(self, settings: Settings) -> None:
        p = settings.processing
        self.output_var.set("audio" if p.audio_only else "video")
        self.mirror_var.set("everything" if p.mirror else "ignore")
        self._set_entry(self.crossfade, f"{p.crossfade_duration_seconds:g}")
        self._set_entry(self.output_dir, shown_folder(settings.output.directory, "output",
                                                      app.ROOT, app.WORKSPACE))

    @staticmethod
    def _set_entry(entry: ttk.Entry, text: str) -> None:
        state = entry.cget("state")
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, text)
        entry.configure(state=state)

    def _fields(self) -> Fields:
        return Fields(source=self.sheet.value(), rows_from=self.rows_from.get(), rows_to=self.rows_to.get(),
                      audio_only=self.output_var.get() == "audio",
                      mirror=self.mirror_var.get() == "everything", countdown=self.countdown.value(),
                      crossfade=self.crossfade.get(), output_dir=self.output_dir.get())

    def _fix_crossfade(self) -> None:
        """Checked by the core as the operator leaves the field; the corrected value is shown."""
        self._set_entry(self.crossfade, f"{correct_crossfade(self.crossfade.get()):g}")

    def _fix_output_dir(self) -> None:
        self._set_entry(self.output_dir, shown_folder(self.output_dir.get(), "output", app.ROOT, app.WORKSPACE))

    def _browse_sheet(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Choose the song list (CSV)", filetypes=CSV_TYPES)
        if path:
            self.sheet.set_value(str(Path(path)))

    def _browse_countdown(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Choose a countdown", filetypes=VIDEO_TYPES)
        if path:
            self.countdown.set_value(str(Path(path)))

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(parent=self.root, title="Save the output to",
                                       initialdir=self.output_dir.get() or str(app.WORKSPACE))
        if path:
            self._set_entry(self.output_dir, str(Path(path)))

    def _unsaved(self) -> bool:
        return settings_from_fields(self._fields(), self.settings, app.ROOT, app.WORKSPACE) != self.settings

    # -- enabled / locked --------------------------------------------------------------

    def _apply_controls(self) -> None:
        c = controls(self.phase, audio_only=self.output_var.get() == "audio",
                     sheet_filled=bool(self.sheet.value().strip()))
        for widget in self.inputs:
            widget.configure(state="normal" if c.inputs else "disabled")
        for radio in self.mirror_radios:
            radio.configure(state="normal" if c.mirror else "disabled")
        for button in self.input_buttons:
            button.set_enabled(c.inputs)
        if c.run_is_stop:
            self.run_button.style(text="STOP", bg=theme.RED)
        else:
            self.run_button.style(text="RUN", bg=theme.NEON)
        self.run_button.set_enabled(c.run_button)
        self.clear_cache_button.set_enabled(c.clear_cache)
        self.est_length.set_enabled(c.est_length)
        self.open_file.set_enabled(c.open_output)
        self.open_folder.set_enabled(c.open_output)

    # -- running -----------------------------------------------------------------------

    def _on_run_button(self) -> None:
        if self.phase is Phase.RUNNING:
            self._confirm_stop()
        elif self.phase not in (Phase.STOPPING,):
            self._start_run()

    def _start_run(self) -> None:
        self._fix_crossfade()
        self._fix_output_dir()
        try:
            request = run_request(self._fields(), self.settings, app.ROOT, app.WORKSPACE)
            validate_settings(request.settings)
            # Refused before anything is saved or downloaded (GUI.md 1.6).
            ensure_folder(app.folder(request.settings.output.directory, "output"), "output")
            self.store.save(request.settings)   # written once, when Run is pressed (SPEC §7)
        except LarbError as e:
            self._popup("Can't run", str(e))
            return
        self.settings = request.settings
        self._clear_log()
        problem = self._remember_inputs()
        if problem:
            self._log_now(LogEvent(Level.WARNING, "start",
                                   f"The Sheet and Countdown fields can't be remembered: {problem}"))
        self.output_path = None
        self.progress.start()
        self.downloads.clear()
        self.phase = Phase.RUNNING
        self._apply_controls()
        self._show_progress(True)
        self._paint_progress()
        self.worker = RunWorker(self.store, request)
        self.worker.start()
        self.root.after(POLL_MS, self._poll)
        self.root.after(TICK_MS, self._tick)

    def _remember_inputs(self) -> str | None:
        """Remember the Sheet and Countdown fields as they are, even empty (GUI.md 1.1, 1.4):
        when Run is pressed and when the window closes. Never the row range: a remembered
        range could silently cut the next run short. Returns why it failed, or None."""
        fields = self._fields()
        return save_last_inputs(self.inputs_file, LastInputs(sheet=fields.source.strip(),
                                                             countdown=fields.countdown.strip()))

    def _close(self) -> None:
        """Close the window for good. The fields are remembered first; there's nobody left
        to tell if that fails, so it's only printed to the console."""
        problem = self._remember_inputs()
        if problem:
            print(f"The Sheet and Countdown fields can't be remembered: {problem}", file=sys.stderr)
        # Pending timers (_poll, _tick, bar sweeps) would fire into destroyed widgets and print
        # "invalid command name". Raw Tcl cancel: after_cancel would delete commands destroy() still owns.
        for timer in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()

    def _start_estimate(self) -> None:
        """Est. Length (GUI.md 3.2): the length a run with the fields as they are would
        plan. Nothing is saved; the fields stay locked until the answer comes."""
        if self.phase not in (Phase.IDLE, Phase.FINISHED, Phase.FAILED):
            return
        self._fix_crossfade()
        self._fix_output_dir()
        try:
            request = run_request(self._fields(), self.settings, app.ROOT, app.WORKSPACE)
            validate_settings(request.settings)
        except LarbError as e:
            self._popup("Can't estimate", str(e))
            return
        self.phase_before_estimate = self.phase
        self.progress_before_estimate = replace(self.progress)
        self.progress.estimating()
        self.phase = Phase.ESTIMATING
        self._apply_controls()
        self._show_progress(True)
        self._paint_progress()
        self.worker = EstimateWorker(self.store, request)
        self.worker.start()
        self.root.after(POLL_MS, self._poll)
        self.root.after(TICK_MS, self._tick)

    def _finish_estimate(self, done: Done) -> None:
        # The progress area goes back to what the last run left ("Finished" / "Stopped: ..."),
        # or, before any run, to hidden and still: painting it would show a sweeping bar.
        self.phase = self.phase_before_estimate
        self.progress = self.progress_before_estimate
        if self.phase is Phase.IDLE:
            self.progress_bar.set(0.0)   # stops the sweep
            self._show_progress(False)
        else:
            self._paint_progress()
        self._apply_controls()
        if self.closing:
            # The window was closed during the estimate: now the usual close (which may
            # still ask about unsaved settings).
            self.closing = False
            self._on_close()
            return
        if done.error is None:
            self._log_now(LogEvent(Level.INFO, "estimate", estimate_log_line(done.result)))
            self._popup("Est. Length", estimate_message(done.result))
        elif not isinstance(done.error, StoppedError):
            self._log_now(LogEvent(Level.ERROR, "estimate", " ".join(str(done.error).split())))
            self._popup("Can't estimate", str(done.error))

    def _confirm_stop(self) -> None:
        answer = ask(self.root, "Stop", "Stop the run?", [("stop", "Stop"), ("keep", "Keep running")],
                     default="keep", colours={"stop": theme.RED}, fonts=self.fonts)
        if answer == "stop" and self.phase is Phase.RUNNING:
            self._stop_run()

    def _stop_run(self) -> None:
        self.phase = Phase.STOPPING
        self.progress.stopping()
        self._paint_progress()
        self._apply_controls()
        self.worker.stop()

    def _poll(self) -> None:
        """Take what the run has said so far. Runs on the window's thread only."""
        worker = self.worker
        if worker is None:
            return
        follow = self._log_at_bottom()   # decided once per batch, before any line is added
        try:
            for _ in range(MAX_EVENTS_PER_POLL):
                try:
                    item = worker.queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(item, Done):
                    self._finish(item)
                    return
                self._handle(item)
        finally:
            if follow and not self.closing:   # closing: the window is already gone
                self.log.see("end")
        self._paint_progress()
        self._paint_downloads()
        self.root.after(POLL_MS, self._poll)

    def _handle(self, event: LogEvent) -> None:
        if self.phase is not Phase.STOPPING:
            self.progress.update(event)
        self.downloads.update(event, time.monotonic())
        # An estimate logs only its result (_finish_estimate), not its steps.
        if shown_in_log(event) and self.phase is not Phase.ESTIMATING:
            self.counts.add(event)
            self._append_log(event)
            self._paint_filters()

    def _finish(self, done: Done) -> None:
        self.worker = None
        self.downloads.clear()
        self._paint_downloads()
        if self.phase is Phase.ESTIMATING:
            self._finish_estimate(done)
            return
        self.progress.finish(done.error)
        self._paint_progress()
        if done.error is None:
            self.phase = Phase.FINISHED
            self.output_path = done.result.output_path
        else:
            self.phase = Phase.FAILED
        self._apply_controls()
        if self.closing:
            self._close()
            return
        if done.error is not None and not isinstance(done.error, StoppedError):
            # Aborted: a blocking pop-up with the core's message (GUI.md "Dialogs").
            self._popup("Run stopped", str(done.error))

    def _tick(self) -> None:
        if self.worker is None:
            return
        self._paint_downloads()
        self.root.after(TICK_MS, self._tick)

    # -- painting ----------------------------------------------------------------------

    def _show_progress(self, shown: bool) -> None:
        if shown:
            self.progress_label.grid()
            self.progress_bar.grid()
        else:
            self.progress_label.grid_remove()
            self.progress_bar.grid_remove()

    def _paint_progress(self) -> None:
        if self.progress.failed:
            # The reason can be long (e.g. a missing column and the ones found): it takes
            # the bar's place and wraps instead of being cut off.
            self.progress_bar.set(0.0)   # hidden: stop any sweep
            self.progress_bar.grid_remove()
            self.progress_label.grid(columnspan=2)
            self.progress_label.configure(text=self.progress.text, style="Stopped.TLabel", width=0,
                                          wraplength=max(self.progress_label.master.winfo_width() - 10, 300))
        else:
            self.progress_bar.grid()
            self.progress_label.grid(columnspan=1)
            self.progress_label.configure(text=self.progress.text, style="Progress.TLabel", width=26,
                                          wraplength=0)
            self.progress_bar.set(self.progress.fraction)

    def _paint_downloads(self) -> None:
        lines = self.downloads.lines(time.monotonic())
        keys = [key for key, _label, _time in lines]
        for key in list(self.download_rows):
            if key not in keys:
                self.download_rows.pop(key)[0].destroy()
        for i, (key, label, spent) in enumerate(lines):
            if key not in self.download_rows:
                row = tk.Frame(self.downloads_box, bg=theme.PANE)
                row.columnconfigure(0, weight=1)
                text = label if len(label) <= LABEL_CHARS else label[:LABEL_CHARS - 1] + "…"
                name = tk.Label(row, text=text, bg=theme.PANE, fg=theme.TEXT, font=self.fonts.normal, anchor="w")
                name.grid(row=0, column=0, sticky="ew", padx=(16, 10))
                bar = SweepBar(row)
                bar.grid(row=0, column=1)
                timer = tk.Label(row, bg=theme.PANE, fg=theme.TEXT, font=self.fonts.normal, width=7, anchor="e")
                timer.grid(row=0, column=2)
                self.download_rows[key] = (row, name, bar, timer)
            row, _name, _bar, timer = self.download_rows[key]
            row.grid(row=i, column=0, sticky="ew")
            timer.configure(text=spent)

    def _paint_filters(self) -> None:
        texts = {LogFilter.ALL: "All", LogFilter.WARNINGS: f"Warnings ({self.counts.warnings})",
                 LogFilter.ERRORS: f"Errors ({self.counts.errors})"}
        active = {LogFilter.ALL: theme.NEON, LogFilter.WARNINGS: theme.ORANGE, LogFilter.ERRORS: theme.RED}
        idle = {LogFilter.ALL: theme.DARK, LogFilter.WARNINGS: theme.shade(theme.ORANGE, theme.INACTIVE_FILTER),
                LogFilter.ERRORS: theme.shade(theme.RED, theme.INACTIVE_FILTER)}
        for log_filter, button in self.filter_buttons.items():
            colour = active[log_filter] if log_filter is self.log_filter else idle[log_filter]
            button.style(text=texts[log_filter], bg=colour, fg=theme.WHITE)

    def _set_filter(self, log_filter: LogFilter) -> None:
        """Display only: filtering never pauses or changes the run."""
        self.log_filter = log_filter
        for level in (Level.INFO, Level.WARNING, Level.ERROR):
            self.log.tag_configure(f"level_{level.name}", elide=not visible(level, log_filter))
        self._paint_filters()
        self.log.see("end")

    # -- log panel ---------------------------------------------------------------------

    def _clear_log(self) -> None:
        self.counts = LogCounts()
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._paint_filters()

    def _log_now(self, event: LogEvent) -> None:
        """Add one line from the window itself (not from a run's queue), counted and
        scrolled like a run's lines."""
        follow = self._log_at_bottom()
        self.counts.add(event)
        self._append_log(event)
        self._paint_filters()
        if follow:
            self.log.see("end")

    def _append_log(self, event: LogEvent) -> None:
        level, stage, text = log_line(event)
        self._write_log_line(level, stage, text)

    def _log_at_bottom(self) -> bool:
        """Follow new lines only while the operator is at the bottom; stay put while they
        have scrolled up to read (GUI.md 2.2). Checked before adding lines: Tk updates
        the scroll position only when it redraws, so it's stale after an insert."""
        return self.log.yview()[1] >= 0.999

    def _write_log_line(self, level: str, stage: str, text: str) -> None:
        """Add one line. The caller scrolls (see _poll), once per batch of lines."""
        tags = ("line", f"level_{level}")
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}\t", (*tags, "muted"))
        self.log.insert("end", f"{level}\t", (*tags, level))
        self.log.insert("end", f"{stage}\t", (*tags, "muted"))
        self.log.insert("end", f"{text}\n", (*tags, level))
        self.log.configure(state="disabled")

    # -- bottom row and open buttons -------------------------------------------------------

    def _clear_cache(self) -> None:
        folder = cache_folder(self.settings.download.cache_directory)
        files, size = cache_summary(folder)
        if not files:
            self._popup("Clear cache", f"The cache is empty ({folder}).")
            return
        answer = ask(self.root, "Clear cache", clear_cache_question(files, size),
                     [("delete", "Delete"), ("cancel", "Cancel")], default="cancel", fonts=self.fonts)
        if answer == "delete":
            deleted = clear_cache(folder)
            follow = self._log_at_bottom()
            self._write_log_line("INFO", "cache", f"Cache cleared: {deleted} file(s) deleted from {folder}")
            if follow:
                self.log.see("end")

    def _open_file(self) -> None:
        if self.output_path:
            self._watch_open(start_open(self.output_path), self.output_path, is_folder=False)

    def _open_folder(self) -> None:
        if self.output_path:
            self._watch_open(start_open(self.output_path.parent), self.output_path.parent, is_folder=True)

    def _watch_open(self, attempt: OpenAttempt, path: Path, is_folder: bool) -> None:
        """When opening fails, say why: a pop-up, and a warning in the log (GUI.md 2.4)."""
        if not attempt.done.is_set():
            self.root.after(OPEN_POLL_MS, self._watch_open, attempt, path, is_folder)
            return
        if attempt.error is None:
            return
        message = open_failure_message(path, is_folder, attempt.error)
        event = LogEvent(Level.WARNING, "output", message.replace("\n", " "))
        follow = self._log_at_bottom()
        self.counts.add(event)
        self._append_log(event)
        self._paint_filters()
        if follow:
            self.log.see("end")
        self._popup("Open folder" if is_folder else "Open file", message)

    # -- dialogs and closing ------------------------------------------------------------

    def _popup(self, title: str, message: str) -> None:
        ask(self.root, title, message, [("ok", "OK")], default="ok", fonts=self.fonts)

    def _on_close(self) -> None:
        if self.phase is Phase.RUNNING:
            answer = ask(self.root, "Close", "A run is in progress. Stop it and close?",
                         [("stop", "Stop and close"), ("keep", "Keep running")], default="keep",
                         colours={"stop": theme.RED}, fonts=self.fonts)
            if answer == "stop" and self.phase is Phase.RUNNING:
                self.closing = True   # closes when the run has ended, so nothing is left running
                self._stop_run()
            return
        if self.phase is Phase.STOPPING:
            self.closing = True
            return
        if self.phase is Phase.ESTIMATING:
            # Nothing to ask: an estimate changes nothing. Stop it; close once it has ended.
            self.closing = True
            self.worker.stop()
            return
        if self._unsaved():
            answer = ask(self.root, "Close", "Save your changes?",
                         [("save", "Save"), ("discard", "Don't save"), ("cancel", "Cancel")],
                         default="save", escape="cancel", fonts=self.fonts)
            if answer == "cancel":
                return
            if answer == "save" and not self._save_settings():
                return
        self._close()

    def _save_settings(self) -> bool:
        self._fix_crossfade()
        self._fix_output_dir()
        settings = settings_from_fields(self._fields(), self.settings, app.ROOT, app.WORKSPACE)
        try:
            validate_settings(settings)
            self.store.save(settings)
        except LarbError as e:
            self._popup("Can't save", str(e))
            return False
        self.settings = settings
        return True
