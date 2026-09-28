"""MediaProcessor implemented with FFmpeg: measuring clips and rendering in one pass.

The render recipe is the one measured in the spike (TECH §10). Read that section
before changing anything here; several lines look optional but aren't.
"""

import re
from pathlib import Path

from larb.adapters.ffmpeg.helper import run_tool
from larb.adapters.ffmpeg.locate import FfmpegTools
from larb.core.errors import RenderError
from larb.core.models import ClipInfo, Level, LogEvent, RenderPlan
from larb.core.ports import EventSink, MediaProcessor

# Hard-coded output format (SPEC §7): the one that plays in Windows' built-in players.
FPS = 30
AUDIO_RATE = 48000
VIDEO_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
              # Must be on the OUTPUT: xfade otherwise picks yuv444p ("High 4:4:4"),
              # which Windows' players can't decode (TECH §10).
              "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
VIDEO_AUDIO_ARGS = ["-c:a", "aac", "-b:a", "192k"]
MP3_ARGS = ["-c:a", "libmp3lame", "-b:a", "192k"]


def _width_for(height: int) -> int:
    """16:9 width for a height, rounded to an even number (encoders need even sizes)."""
    return round(height * 16 / 9 / 2) * 2


class FfmpegProcessor(MediaProcessor):
    """Args:
        tools: FFmpeg/ffprobe found by locate.find_ffmpeg().
        work_dir: Folder (inside workspace/) for temporary files such as filter graphs.
        events: Where to log the exact commands (at DEBUG level).
    """

    def __init__(self, tools: FfmpegTools, work_dir: Path, events: EventSink) -> None:
        self._tools = tools
        self._work_dir = work_dir
        self._events = events
        work_dir.mkdir(parents=True, exist_ok=True)

    def describe(self) -> str:
        return f"FFmpeg {self._tools.version_text} ({self._tools.origin})"

    def _log_command(self, command: str) -> None:
        self._events.emit(LogEvent(Level.DEBUG, "ffmpeg", command))

    # -- measuring -------------------------------------------------------------

    def measure(self, path: Path, start_s: float, end_s: float | None) -> ClipInfo:
        probe = run_tool(self._tools.ffprobe, ["-v", "error", "-show_entries", "format=duration",
                                               "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                         self._log_command)
        try:
            duration = float(probe.stdout.strip())
        except ValueError:
            raise RenderError(f"Can't read the length of {path.name}") from None

        args = ["-hide_banner", "-nostats", "-ss", f"{start_s:.3f}"]
        if end_s is not None:
            args += ["-t", f"{max(end_s - start_s, 0.0):.3f}"]
        # volumedetect reports the sample peak ("max_volume") of the range.
        args += ["-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"]
        result = run_tool(self._tools.ffmpeg, args, self._log_command)
        match = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", result.stderr)
        # No match = nothing was decoded (range starts after the end of the file).
        peak = float(match.group(1)) if match else float("-inf")
        return ClipInfo(duration_s=duration, peak_db=peak)

    # -- rendering ---------------------------------------------------------------

    def _graph(self, plan: RenderPlan) -> str:
        """The filter graph for the whole compilation (TECH §10 recipe)."""
        video, lines = not plan.audio_only, []
        h, w = plan.height, _width_for(plan.height)
        for i, seg in enumerate(plan.segments):
            # Gain first, then make every segment's format identical: the inputs
            # differ (44.1 vs 48 kHz, different sizes and frame rates).
            # apad + atrim: exactly the planned length, padded with silence or cut. An
            # Opus file's container reports a few ms more than decodes (TECH §16), which
            # added up over a long list; any other source a few ms off is covered too.
            dur = f"{seg.duration_s:.6f}"
            lines.append(f"[{i}:a]volume={seg.gain_db:.2f}dB,aresample={AUDIO_RATE},"
                         f"aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
                         f"apad=whole_dur={dur},atrim=duration={dur}[a{i}]")
            if video:
                flip = ",hflip" if seg.mirror else ""
                lines.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                             f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p"
                             f"{flip},setpts=PTS-STARTPTS[v{i}]")
        n, d = len(plan.segments), plan.crossfade_s
        # acrossfade needs no lengths; xfade needs the offset of each join,
        # which is why every segment's length must be known up front.
        prev_a, prev_v, length = "a0", "v0", plan.segments[0].duration_s
        for i in range(1, n):
            lines.append(f"[{prev_a}][a{i}]acrossfade=d={d}:c1=tri:c2=tri[ax{i}]")
            prev_a = f"ax{i}"
            if video:
                lines.append(f"[{prev_v}][v{i}]xfade=transition=fade:duration={d}"
                             f":offset={length - d:.3f}[vx{i}]")
                prev_v = f"vx{i}"
            length += plan.segments[i].duration_s - d

        # End fade-out: the last fade_out_s seconds fade to silence and to black,
        # ending exactly at the end. The fades only change volume and brightness,
        # so the length stays the same.
        f = plan.fade_out_s
        if f > 0:
            start = max(length - f, 0.0)
            # curve=qua: volume falls with the square of the time left, so the tail is
            # inaudible sooner than with the default straight line (maintainer choice).
            lines.append(f"[{prev_a}]afade=t=out:st={start:.3f}:d={f}:curve=qua[aout]")
            if video:
                lines.append(f"[{prev_v}]fade=t=out:st={start:.3f}:d={f}:color=black[vout]")
        else:
            lines.append(f"[{prev_a}]anull[aout]")
            if video:
                lines.append(f"[{prev_v}]null[vout]")
        return ";\n".join(lines)

    def render(self, plan: RenderPlan, output_path: Path) -> Path:
        args = ["-hide_banner", "-nostats", "-y"]
        for seg in plan.segments:
            # Input-side seek + length: exact because we re-encode, and avoids decoding whole songs.
            args += ["-ss", f"{seg.start_s:.3f}", "-t", f"{seg.duration_s:.3f}", "-i", str(seg.path)]

        # The graph goes in a file: on the command line it would pass Windows'
        # 32,767-character limit at around 50 songs (TECH §3). "-/option <file>" reads the
        # option's value from a file (FFmpeg 7.1+, guaranteed by locate.MIN_VERSION).
        graph_file = self._work_dir / f"{output_path.stem}.graph.txt"
        graph_file.write_text(self._graph(plan), encoding="utf-8")
        args += ["-/filter_complex", str(graph_file)]

        if plan.audio_only:
            args += ["-map", "[aout]", *MP3_ARGS]
        else:
            args += ["-map", "[vout]", *VIDEO_ARGS, "-map", "[aout]", *VIDEO_AUDIO_ARGS]

        # Straight to output_path: the core picks a temporary name and renames the
        # file only after checking it. A failed run leaves its partial file for the
        # core to name, and the graph file here for debugging.
        run_tool(self._tools.ffmpeg, [*args, str(output_path)], self._log_command)
        graph_file.unlink(missing_ok=True)
        return output_path
