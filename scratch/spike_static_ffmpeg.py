"""Spike: static_ffmpeg first-use fetch — time, size, location, version."""
import os, subprocess, sys, time
from pathlib import Path

t0 = time.perf_counter()
from static_ffmpeg import run
ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
dt = time.perf_counter() - t0
print(f"fetch/resolve took {dt:.1f}s")
print("ffmpeg :", ffmpeg)
print("ffprobe:", ffprobe)
bindir = Path(ffmpeg).parent
total = sum(f.stat().st_size for f in bindir.rglob("*") if f.is_file())
print(f"bin dir: {bindir}  total {total/1e6:.1f} MB")
for f in sorted(bindir.rglob("*")):
    if f.is_file():
        print(f"  {f.relative_to(bindir)}  {f.stat().st_size/1e6:.1f} MB")
out = subprocess.run([ffmpeg, "-hide_banner", "-version"], capture_output=True, text=True).stdout
print(out.splitlines()[0])
print("xfade present:", "xfade" in subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True).stdout)
print("PATH mentions static_ffmpeg:", "static_ffmpeg" in os.environ["PATH"])
