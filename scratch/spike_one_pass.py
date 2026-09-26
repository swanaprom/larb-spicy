"""Spike: can trim + mirror + crossfade + countdown insertion be ONE FFmpeg pass?

Sequence built: countdown -> song1 -> countdown -> song2 -> ...
with a crossfade of D seconds at every join.

Throwaway code. Only the findings matter (docs/TECH.md).
"""
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

from static_ffmpeg import run

FFMPEG, FFPROBE = run.get_or_fetch_platform_executables_else_raise()
ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
OUT = ROOT / "workspace" / "spike"
OUT.mkdir(parents=True, exist_ok=True)

W, H, FPS, RATE = 1280, 720, 30, 48000


def ffrun(args: list[str]) -> float:
    """Run ffmpeg with binary kept separate from args; return wall time."""
    cmd = [FFMPEG, "-hide_banner", "-y", *args]
    print("CMD:", subprocess.list2cmdline(cmd))
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    dt = time.perf_counter() - t0
    if p.returncode != 0:
        print(p.stderr[-3000:])
        raise SystemExit(f"ffmpeg failed ({p.returncode})")
    return dt


def probe(path: Path) -> dict:
    p = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type,duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(p.stdout)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def build(segments, out: Path, video: bool, mirror: bool, d: float, acodec: list[str],
          pad: float = 0.0):
    """segments: list of (path, start, end, is_countdown). end=None -> whole file.

    pad: extend each SONG clip by this many seconds on both sides, clamped to
    [0, real file length]. Countdowns are never padded.
    """
    args, vf, af = [], [], []
    durs = []
    for i, (path, start, end, is_cd) in enumerate(segments):
        real = duration(path)
        if end is None:
            end = real
        if end > real:  # FFmpeg would exit 0 with corrupt output (TECH §10)
            raise SystemExit(f"segment {i}: end {end}s past real length {real:.3f}s of {path.name}")
        if pad and not is_cd:
            start, end = max(0.0, start - pad), min(real, end + pad)
        dur = end - start
        durs.append(dur)
        # Input-side seek + -t: accurate when re-encoding, and avoids decoding the whole song.
        args += ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path)]
        # Normalize audio so every join has identical format (inputs differ: 44.1k vs 48k).
        af.append(f"[{i}:a]aresample={RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                  f"asetpts=PTS-STARTPTS[a{i}]")
        if video:
            flip = ",hflip" if (mirror and not is_cd) else ""
            vf.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                      f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p"
                      f"{flip},setpts=PTS-STARTPTS[v{i}]")

    if len(segments) == 1:  # no joins -> just rename the streams
        af.append("[a0]anull[aout]")
        if video:
            vf.append("[v0]null[vout]")
    # Audio chain: acrossfade needs no durations.
    prev = "a0"
    for i in range(1, len(segments)):
        nxt = f"ax{i}" if i < len(segments) - 1 else "aout"
        af.append(f"[{prev}][a{i}]acrossfade=d={d}:c1=tri:c2=tri[{nxt}]")
        prev = nxt
    # Video chain: xfade needs offset = running output length - d  -> durations must be known.
    if video:
        prev, length = "v0", durs[0]
        for i in range(1, len(segments)):
            nxt = f"vx{i}" if i < len(segments) - 1 else "vout"
            vf.append(f"[{prev}][v{i}]xfade=transition=fade:duration={d}:offset={length - d:.3f}[{nxt}]")
            length += durs[i] - d
            prev = nxt

    # Graph goes in a file: the command line would pass Windows' 32 767-char limit at ~50 songs.
    graph_file = out.with_suffix(out.suffix + ".graph.txt")
    graph_file.write_text(";\n".join(vf + af), encoding="utf-8")
    args += ["-/filter_complex", str(graph_file)]
    if video:
        # yuv420p on OUTPUT: xfade otherwise negotiates yuv444p ("High 4:4:4"), which
        # Windows' built-in players can't decode. Video mapped first = player-friendly.
        args += ["-map", "[vout]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                 "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    args += ["-map", "[aout]", *acodec, str(out)]
    expected = sum(durs) - d * (len(durs) - 1)
    dt = ffrun(args)
    info = probe(out)
    print(f"-> {out.name}: took {dt:.1f}s, expected {expected:.3f}s, got format {float(info['format']['duration']):.3f}s")
    for s in info["streams"]:
        print(f"   stream {s['codec_type']}: {s.get('duration')}")
    return dt, expected, durs


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "audio"
    D = 1.0
    if mode == "audio":
        cd = FIX / "countdown" / "!countdown.mp3"
        segs = [(cd, 0, None, True),
                (FIX / "XG - GRL GVNG (Instrumental).mp3", 30.0, 60.0, False),
                (cd, 0, None, True),
                (FIX / "sewer. [Instrumental].mp3", 10.0, 40.0, False)]
        build(segs, OUT / "audio.mp3", False, False, D, ["-c:a", "libmp3lame", "-b:a", "192k"])
        build(segs, OUT / "audio.m4a", False, False, D, ["-c:a", "aac", "-b:a", "192k"])
    elif mode == "video":
        cd = FIX / "countdown" / "!countdown.mp4"
        small = next(FIX.glob("*.mp4"))
        big = next((ROOT / "workspace" / "test_media").glob("*.mp4"))
        segs = [(cd, 0, None, True),
                (big, 30.0, 60.0, False),
                (cd, 0, None, True),
                (small, 1.0, 6.0, False)]
        build(segs, OUT / "video_mirror.mp4", True, True, D, ["-c:a", "aac", "-b:a", "192k"])
