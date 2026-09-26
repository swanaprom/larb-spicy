"""Spike: full download + FFmpeg trim  vs  yt-dlp --download-sections.

Measures wall time, file size, and trimmed-clip duration/start accuracy.
Throwaway code. Only the findings matter (docs/TECH.md).
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spike_one_pass as s  # reuse FFMPEG/FFPROBE, ffrun, probe

ROOT = s.ROOT
YTDLP = ROOT / ".venv" / "Scripts" / "yt-dlp.exe"
DL = ROOT / "workspace" / "spike" / "dl"
DL.mkdir(parents=True, exist_ok=True)
FFDIR = str(Path(s.FFMPEG).parent)

URL = "https://www.youtube.com/watch?v=oKBwWQI-IoI"
START, END = 27.0, 64.0          # sheet row: "0:27 - 1. 04"
VFMT = "bv*[height<=720]+ba/b[height<=720]"
AFMT = "ba/b"


def ytdlp(tag: str, extra: list[str], js: list[str] | None = None) -> tuple[float, str]:
    out = DL / f"{tag}.%(ext)s"
    cmd = [str(YTDLP), "--no-playlist", "--ffmpeg-location", FFDIR, "--force-overwrites",
           "--no-progress", *(js or []), *extra, "-o", str(out), URL]
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    dt = time.perf_counter() - t0
    if p.returncode:
        print(p.stdout[-1500:], p.stderr[-1500:])
        raise SystemExit(f"yt-dlp failed for {tag}")
    files = [f for f in DL.glob(f"{tag}.*") if not f.name.endswith((".part", ".ytdl"))]
    return dt, str(files[0])


def report(tag: str, dt: float, path: str, extra: str = ""):
    info = s.probe(Path(path))
    size = Path(path).stat().st_size / 1e6
    fmt = info["format"]
    print(f"{tag:28s} {dt:6.1f}s  {size:7.1f} MB  dur {float(fmt['duration']):7.3f}s  {extra}")


def start_time(path: str) -> str:
    p = subprocess.run([s.FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,start_time",
                        "-of", "compact", path], capture_output=True, text=True)
    return p.stdout.strip().replace("\n", " ; ")


if __name__ == "__main__":
    js = ["--js-runtimes", "node"] if "node" in sys.argv else None
    sfx = "_node" if js else ""
    print(f"target clip {START}-{END} = {END-START:.1f}s   js={js}")

    # A: full audio + ffmpeg trim
    dt, full = ytdlp("A_full_audio" + sfx, ["-f", AFMT], js)
    report("A download full audio", dt, full)
    trim = str(DL / f"A_trim{sfx}.m4a")
    t = s.ffrun(["-ss", str(START), "-t", str(END - START), "-i", full, "-c:a", "aac", trim])
    report("A + ffmpeg trim", dt + t, trim, start_time(trim))

    # B: audio sections
    dt, sec = ytdlp("B_sec_audio" + sfx, ["-f", AFMT, "--download-sections", f"*{START}-{END}"], js)
    report("B sections audio", dt, sec, start_time(sec))

    # C: full video <=720p + ffmpeg trim
    dt, full = ytdlp("C_full_video" + sfx, ["-f", VFMT], js)
    report("C download full video", dt, full)
    trim = str(DL / f"C_trim{sfx}.mp4")
    t = s.ffrun(["-ss", str(START), "-t", str(END - START), "-i", full,
                 "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", trim])
    report("C + ffmpeg trim", dt + t, trim, start_time(trim))

    # D: video sections, no keyframe forcing
    dt, sec = ytdlp("D_sec_video" + sfx, ["-f", VFMT, "--download-sections", f"*{START}-{END}"], js)
    report("D sections video", dt, sec, start_time(sec))

    # E: video sections + --force-keyframes-at-cuts
    dt, sec = ytdlp("E_sec_video_kf" + sfx, ["-f", VFMT, "--download-sections", f"*{START}-{END}",
                                             "--force-keyframes-at-cuts"], js)
    report("E sections video + kf", dt, sec, start_time(sec))
