"""MediaProcessor implemented with FFmpeg: measuring clips and rendering in one pass.

The render recipe is the one measured in the spike (TECH §10). Read that section
before changing anything here; several lines look optional but aren't.
"""

import os
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
SCRIPT_FILE_OPTION_VERSION = (7, 1)  # "-/filter_complex <file>" exists from FFmpeg 7.1


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
            lines.append(f"[{i}:a]volume={seg.gain_db:.2f}dB,aresample={AUDIO_RATE},"
                         f"aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]")
            if video:
                flip = ",hflip" if seg.mirror else ""
                lines.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                             f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p"
                             f"{flip},setpts=PTS-STARTPTS[v{i}]")
        n, d = len(plan.segments), plan.crossfade_s
        if n == 1:
            lines.append("[a0]anull[aout]")
            if video:
                lines.append("[v0]null[vout]")
        # acrossfade needs no lengths; xfade needs the offset of each join,
        # which is why every segment's length must be known up front.
        prev_a, prev_v, length = "a0", "v0", plan.segments[0].duration_s
        for i in range(1, n):
            last = i == n - 1
            out_a = "aout" if last else f"ax{i}"
            lines.append(f"[{prev_a}][a{i}]acrossfade=d={d}:c1=tri:c2=tri[{out_a}]")
            prev_a = out_a
            if video:
                out_v = "vout" if last else f"vx{i}"
                lines.append(f"[{prev_v}][v{i}]xfade=transition=fade:duration={d}"
                             f":offset={length - d:.3f}[{out_v}]")
                prev_v = out_v
            length += plan.segments[i].duration_s - d
        return ";\n".join(lines)

    def render(self, plan: RenderPlan, output_path: Path) -> Path:
        args = ["-hide_banner", "-nostats", "-y"]
        for seg in plan.segments:
            # Input-side seek + length: exact because we re-encode, and avoids decoding whole songs.
            args += ["-ss", f"{seg.start_s:.3f}", "-t", f"{seg.duration_s:.3f}", "-i", str(seg.path)]

        # The graph goes in a file: on the command line it would pass Windows'
        # 32,767-character limit at around 50 songs (TECH §3).
        graph_file = self._work_dir / f"{output_path.stem}.graph.txt"
        graph_file.write_text(self._graph(plan), encoding="utf-8")
        version = self._tools.version
        if version is None or version >= SCRIPT_FILE_OPTION_VERSION:
            args += ["-/filter_complex", str(graph_file)]
        else:
            args += ["-filter_complex_script", str(graph_file)]

        if plan.audio_only:
            args += ["-map", "[aout]", *MP3_ARGS]
        else:
            args += ["-map", "[vout]", *VIDEO_ARGS, "-map", "[aout]", *VIDEO_AUDIO_ARGS]

        # Render to a temporary name, then rename: a crash never leaves a
        # half-written file under the final name.
        partial = output_path.with_name(f"{output_path.stem}.rendering{output_path.suffix}")
        try:
            run_tool(self._tools.ffmpeg, [*args, str(partial)], self._log_command)
            os.replace(partial, output_path)
        finally:
            partial.unlink(missing_ok=True)
        graph_file.unlink(missing_ok=True)
        return output_path
