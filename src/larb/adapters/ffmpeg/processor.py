"""MediaProcessor implemented with FFmpeg: measuring clips and rendering.

Audio-only runs render in one pass. Video renders in fixed chunks that are joined
without re-encoding, with the audio rendered in one pass and added at the end.
The recipes were measured (TECH §10, §16). Read those sections before changing
anything here; several lines look optional but aren't.
"""

import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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

# Video chunk size, in segments (a song and its countdown are 2): 6 songs. Hard-coded,
# not a setting: FFmpeg's memory grows with every input it has open (TECH §14). At
# 720p a 6-song chunk peaked at 0.83 GB on the i5-6400 test PC, well under the ~2 GB
# target, leaving room for 60 fps sources or a larger max_height (TECH §16). Keep it
# EVEN, so every cut falls inside a countdown rather than inside a song.
CHUNK_SEGMENTS = 12
# One decoder thread per input: ~9% less memory at the same speed (TECH §16).
DECODER_ARGS = ["-threads", "1"]


def _width_for(height: int) -> int:
    """16:9 width for a height, rounded to an even number (encoders need even sizes)."""
    return round(height * 16 / 9 / 2) * 2


class FfmpegProcessor(MediaProcessor):
    """Args:
        tools: FFmpeg/ffprobe found by locate.find_ffmpeg().
        work_dir: Folder (inside workspace/) for temporary files such as filter graphs
            and video chunks.
        events: Where to log the exact commands (at DEBUG level) and render progress.
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

    def render(self, plan: RenderPlan, output_path: Path) -> Path:
        # Straight to output_path: the core picks a temporary name and renames the
        # file only after checking it. A failed run leaves its partial file for the
        # core to name, and its graph file in work_dir for debugging.
        if plan.audio_only:
            self._run_pass(plan, output_path, audio=True, video=False)   # one pass: fast and small
        else:
            self._render_video(plan, output_path)
        return output_path

    def _render_video(self, plan: RenderPlan, output_path: Path) -> None:
        """Video in fixed chunks, audio in one pass, then joined without re-encoding
        (TECH §10 method C, §16). Used for every video run, however short, so there is
        one code path: in one pass, FFmpeg's memory grows with every song (TECH §14)."""
        chunks = split_into_chunks(plan, CHUNK_SEGMENTS)
        stem = output_path.stem
        audio_file = self._work_dir / f"{stem}.audio.m4a"
        chunk_files = [self._work_dir / f"{stem}.chunk{n:03d}.mp4" for n in range(1, len(chunks) + 1)]
        list_file = self._work_dir / f"{stem}.chunks.txt"
        try:
            # The whole list's audio in one pass (the audio-only graph), so there is no
            # audio seam at the chunk joins: joining AAC by copying drops a few ms there
            # (TECH §10, method B). It runs alongside the video chunks: it needs little
            # CPU or memory, and one after the other cost ~15% more time (TECH §16).
            with ThreadPoolExecutor(max_workers=1) as audio_worker:
                audio_done = audio_worker.submit(self._run_pass, plan, audio_file, audio=True, video=False)
                for n, (chunk, chunk_file) in enumerate(zip(chunks, chunk_files), 1):
                    self._run_pass(chunk, chunk_file, audio=False, video=True)
                    self._check_frames(chunk_file, chunk, f"video part {n}")
                    self._events.emit(LogEvent(Level.INFO, "render", f"video part {n}/{len(chunks)} done",
                                               progress=(n, len(chunks))))
                audio_done.result()   # raises the audio pass's error, if it had one
            # Concat list: one "file '<path>'" line per chunk; a ' inside a path is written '\''.
            quote = "'\\''"
            list_file.write_text("".join(f"file '{str(f).replace(chr(39), quote)}'\n" for f in chunk_files),
                                 encoding="utf-8")
            run_tool(self._tools.ffmpeg, ["-hide_banner", "-nostats", "-y",
                                          "-f", "concat", "-safe", "0", "-i", str(list_file),
                                          "-i", str(audio_file), "-map", "0:v", "-map", "1:a",
                                          "-c", "copy", "-movflags", "+faststart", str(output_path)],
                     self._log_command)
            self._check_frames(output_path, plan, "joined video")
        finally:
            for f in (audio_file, list_file, *chunk_files):
                f.unlink(missing_ok=True)

    def _run_pass(self, plan: RenderPlan, out: Path, audio: bool, video: bool) -> None:
        """One FFmpeg run: trim, format, crossfade and fade the plan's segments into `out`.
        Audio goes to .mp3 on its own (audio-only mode), else AAC."""
        args = ["-hide_banner", "-nostats", "-y"]
        for seg in plan.segments:
            # Input-side seek + length: exact because we re-encode, and avoids decoding whole
            # songs. -an / -vn: leave out the stream this pass doesn't use.
            args += ["-ss", f"{seg.start_s:.6f}", "-t", f"{seg.duration_s:.6f}", *DECODER_ARGS,
                     *([] if audio else ["-an"]), *([] if video else ["-vn"]), "-i", str(seg.path)]

        # The graph goes in a file: on the command line it would pass Windows'
        # 32,767-character limit at around 50 songs (TECH §3). "-/option <file>" reads the
        # option's value from a file (FFmpeg 7.1+, guaranteed by locate.MIN_VERSION).
        graph_file = self._work_dir / f"{out.stem}.graph.txt"
        graph_file.write_text(_graph(plan, audio, video), encoding="utf-8")
        args += ["-/filter_complex", str(graph_file)]
        if video:
            args += ["-map", "[vout]", "-frames:v", str(frames_for(plan.expected_duration_s)), *VIDEO_ARGS]
        if audio:
            args += ["-map", "[aout]", *(MP3_ARGS if out.suffix == ".mp3" else VIDEO_AUDIO_ARGS)]
        run_tool(self._tools.ffmpeg, [*args, str(out)], self._log_command)
        graph_file.unlink(missing_ok=True)   # kept only when the run failed, for debugging

    def _check_frames(self, path: Path, plan: RenderPlan, what: str) -> None:
        """Goal 1: a chunk a frame too long or short would shift every later chunk
        against the one-pass audio. Checked for each chunk and for the joined video."""
        probe = run_tool(self._tools.ffprobe, ["-v", "error", "-select_streams", "v:0", "-count_packets",
                                               "-show_entries", "stream=nb_read_packets",
                                               "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                         self._log_command)
        try:
            frames = int(probe.stdout.strip())
        except ValueError:
            raise RenderError(f"Can't count the frames of the {what} ({path.name})") from None
        planned = frames_for(plan.expected_duration_s)
        if frames != planned:
            raise RenderError(f"The {what} has {frames} frames but should have {planned} "
                              f"({plan.expected_duration_s:.3f} s at {FPS} fps)")


def frames_for(seconds: float) -> int:
    """Frames in this many seconds of output video. Exact for the whole-frame chunks
    (split_into_chunks); the last chunk ends within half a frame of its audio."""
    return round(seconds * FPS)


def _graph(plan: RenderPlan, audio: bool, video: bool) -> str:
    """The filter graph for the plan's audio and/or video (TECH §10 recipe)."""
    lines = []
    h, w = plan.height, _width_for(plan.height)
    for i, seg in enumerate(plan.segments):
        dur = f"{seg.duration_s:.6f}"
        if audio:
            # Gain first, then make every segment's format identical: the inputs
            # differ (44.1 vs 48 kHz, different sizes and frame rates).
            # apad + atrim: exactly the planned length, padded with silence or cut. An
            # Opus file's container reports a few ms more than decodes (TECH §16), which
            # added up over a long list; any other source a few ms off is covered too.
            lines.append(f"[{i}:a]volume={seg.gain_db:.2f}dB,aresample={AUDIO_RATE},"
                         f"aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
                         f"apad=whole_dur={dur},atrim=duration={dur}[a{i}]")
        if video:
            # tpad + trim: exactly the planned length, repeating the last frame when the
            # video stream is shorter than the file (TECH §16), as apad does for audio.
            flip = ",hflip" if seg.mirror else ""
            lines.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                         f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p"
                         f"{flip},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={dur},"
                         f"trim=duration={dur}[v{i}]")
    # acrossfade needs no lengths; xfade needs the offset of each join,
    # which is why every segment's length must be known up front.
    # Each join has its own crossfade length (the core shortens it for short clips).
    prev_a, prev_v, length = "a0", "v0", plan.segments[0].duration_s
    for i in range(1, len(plan.segments)):
        d = plan.crossfades_s[i - 1]
        if audio:
            lines.append(f"[{prev_a}][a{i}]acrossfade=d={d:.6f}:c1=tri:c2=tri[ax{i}]")
            prev_a = f"ax{i}"
        if video:
            lines.append(f"[{prev_v}][v{i}]xfade=transition=fade:duration={d:.6f}"
                         f":offset={length - d:.6f}[vx{i}]")
            prev_v = f"vx{i}"
        length += plan.segments[i].duration_s - d

    # End fade-out: the last fade_out_s seconds fade to silence and to black,
    # ending exactly at the end. The fades only change volume and brightness,
    # so the length stays the same.
    f = plan.fade_out_s
    start = max(length - f, 0.0)
    if audio:
        # curve=qua: volume falls with the square of the time left, so the tail is
        # inaudible sooner than with the default straight line (maintainer choice).
        lines.append(f"[{prev_a}]afade=t=out:st={start:.6f}:d={f:.6f}:curve=qua[aout]" if f > 0
                     else f"[{prev_a}]anull[aout]")
    if video:
        # fps + tpad: xfade offsets aren't whole frames, so frames after a join come off
        # the 1/30 s grid; fps puts them back, and the repeated last frame means the
        # video is never short. The pass then stops at exactly frames_for() frames
        # (-frames:v), so chunks join frame-exact.
        fade = f"fade=t=out:st={start:.6f}:d={f:.6f}:color=black," if f > 0 else ""
        lines.append(f"[{prev_v}]{fade}fps={FPS},tpad=stop_mode=clone:stop_duration=1[vout]")
    return ";\n".join(lines)


def split_into_chunks(plan: RenderPlan, chunk_segments: int) -> list[RenderPlan]:
    """Split a plan into consecutive chunks whose videos join back into the plan's video.

    A cut goes inside segment chunk_segments, 2 x chunk_segments, ... With an even
    chunk size that is always a countdown, since the core puts one before every song.
    It lands on a frame boundary within the part of that segment that plays on its
    own, between its two crossfades; the core's crossfade rule keeps that part at
    least one frame long. So every chunk but the last is a whole number of frames,
    and the joined video has the same timing as a one-pass render.

    Returns:
        One plan per chunk, in order. Only their video is rendered: the audio comes
        from the whole plan in one pass.
    """
    segs, fades = plan.segments, plan.crossfades_s
    starts, t = [], 0.0          # where each segment starts in the output
    for i, seg in enumerate(segs):
        starts.append(t)
        t += seg.duration_s - (fades[i] if i < len(fades) else 0.0)

    cuts = []                    # (segment index, seconds into that segment)
    for i in range(chunk_segments, len(segs) - 1, chunk_segments):
        solo_from = starts[i] + fades[i - 1]
        solo_to = starts[i] + segs[i].duration_s - fades[i]
        middle = (solo_from + solo_to) / 2
        # The first frame boundary after the middle (TECH §10), or the one before it
        # when that is past the solo part (possible when the solo part is ~1 frame).
        cut = math.ceil(round(middle * FPS, 6)) / FPS
        if cut > solo_to + 1e-9:
            cut = math.floor(round(middle * FPS, 6)) / FPS
        cuts.append((i, cut - starts[i]))

    chunks, first, head = [], 0, 0.0    # head: how much of the first segment the previous chunk used
    for cut_index, into in [*cuts, (None, 0.0)]:
        last = len(segs) - 1 if cut_index is None else cut_index
        part = list(segs[first:last + 1])
        part[0] = replace(part[0], start_s=part[0].start_s + head)
        if cut_index is not None:
            part[-1] = replace(part[-1], end_s=segs[cut_index].start_s + into)
        chunks.append(RenderPlan(tuple(part), fades[first:last], plan.audio_only, plan.height,
                                 fade_out_s=plan.fade_out_s if cut_index is None else 0.0))
        first, head = last, into
    return chunks
