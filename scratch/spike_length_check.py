"""Spike: catch "end_time past song length" at manifest stage, before downloading.

Idea: ask YouTube for metadata only (yt-dlp extract_info(download=False)),
compare info["duration"] with end_time. Then, for rows that pass, reuse the
same info dict to download (so metadata isn't fetched twice).

Usage: python spike_length_check.py [node]   ("node" -> --js-runtimes node)
Throwaway code. Only the findings matter (docs/TECH.md).
"""
import sys
import time
from pathlib import Path

import yt_dlp
from static_ffmpeg import run

import test_parser

FFMPEG, _ = run.get_or_fetch_platform_executables_else_raise()
DL = Path(__file__).resolve().parent.parent / "workspace" / "spike" / "dl2"
DL.mkdir(parents=True, exist_ok=True)

USE_NODE = "node" in sys.argv
BASE_OPTS = {
    "quiet": True,
    "no_warnings": False,
    "noplaylist": True,
    "ffmpeg_location": str(Path(FFMPEG).parent),
    # 720p cap, prefer H.264 + AAC (a sort, so it still falls back if missing)
    "format_sort": ["vcodec:h264", "res:720", "acodec:m4a"],
}
if USE_NODE:
    BASE_OPTS["js_runtimes"] = {"node": {}}


def check_row(ydl, url, start, end):
    """Return (ok, reason, info, seconds)."""
    t0 = time.perf_counter()
    try:
        info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        return False, f"unavailable: {e.msg if hasattr(e, 'msg') else e}", None, time.perf_counter() - t0
    dt = time.perf_counter() - t0
    dur = info.get("duration")
    if dur is None:
        return False, "no duration in metadata (live stream?)", info, dt
    if end > dur:
        return False, f"end_time {end}s is past video length {dur}s", info, dt
    if start >= end:
        return False, f"start {start}s >= end {end}s", info, dt
    return True, f"ok (video {dur}s)", info, dt


if __name__ == "__main__":
    manifest = test_parser.get_manifest()
    rows = [(r[0], r[2], r[3], r[4]) for r in manifest]
    # synthetic bad rows to prove the check catches them
    rows += [("OVERRUN test", rows[0][1], 100, 9999),
             ("UNAVAILABLE test", "https://www.youtube.com/watch?v=aaaaaaaaaaa", 0, 10)]
    print(f"js runtime: {'node' if USE_NODE else 'none'}")
    good = []
    with yt_dlp.YoutubeDL({**BASE_OPTS, "outtmpl": str(DL / "%(id)s.%(ext)s")}) as ydl:
        for title, url, start, end in rows:
            ok, reason, info, dt = check_row(ydl, url, start, end)
            print(f"  [{'OK ' if ok else 'ERR'}] {title:18s} {start}-{end}  {reason}   (metadata {dt:.1f}s)")
            if ok:
                good.append((title, info))

        if "--download" in sys.argv:
            for title, info in good:
                t0 = time.perf_counter()
                res = ydl.process_ie_result(info, download=True)  # reuse metadata
                fmt = res.get("format_id")
                print(f"  downloaded {title}: format {fmt} {res.get('width')}x{res.get('height')} "
                      f"{res.get('vcodec')}/{res.get('acodec')} in {time.perf_counter() - t0:.1f}s")
