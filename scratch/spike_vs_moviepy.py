"""Spike: our pipeline end-to-end on the same rows the moviepy prototype used.

Same inputs as workspace/spike/moviepy/data/entry.csv (first 5 rows), same
settings where they map: 1 s padding, 1 s fades/crossfades, no mirror,
5 parallel downloads, outputs both .mp4 and .mp3 (the prototype writes both).
Throwaway code. Only the findings matter (docs/TECH.md).
"""
import concurrent.futures
import csv
import sys
import time
from pathlib import Path

import yt_dlp

sys.path.insert(0, str(Path(__file__).parent))
import spike_one_pass as s

CSV = s.ROOT / "workspace" / "spike" / "moviepy" / "data" / "entry.csv"
DL = s.ROOT / "workspace" / "spike" / "ours_dl"
OUT = s.ROOT / "workspace" / "spike" / "ours_out"
DL.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
CD = s.FIX / "countdown" / "!countdown.mp4"
OPTS = {"quiet": True, "noprogress": True, "noplaylist": True,
        "ffmpeg_location": str(Path(s.FFMPEG).parent),
        "format_sort": ["vcodec:h264", "res:720", "acodec:m4a"],
        "js_runtimes": {"node": {}},
        "outtmpl": str(DL / "%(id)s.%(ext)s")}


def hms(t: str) -> int:
    return sum(int(p) * 60 ** i for i, p in enumerate(reversed(t.strip().split(":"))))


def fetch(row):
    url, start, end = row
    with yt_dlp.YoutubeDL(OPTS) as ydl:
        info = ydl.extract_info(url, download=False)          # metadata check first
        if end > info["duration"]:
            raise ValueError(f"{url}: end {end} past {info['duration']}")
        res = ydl.process_ie_result(info, download=True)
        return Path(res["requested_downloads"][0]["filepath"]), start, end


if __name__ == "__main__":
    with open(CSV, encoding="utf-8", newline="") as f:
        rows = [(r[9], hms(r[10]), hms(r[11])) for r in list(csv.reader(f))[1:]]
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        songs = list(ex.map(fetch, rows))
    t_dl = time.perf_counter() - t0
    segs = []
    for p, a, b in songs:
        segs += [(CD, 0, None, True), (p, float(a), float(b), False)]
    t_v, exp, _ = s.build(segs, OUT / "final_output.mp4", True, False, 1.0, ["-c:a", "aac", "-b:a", "192k"], pad=1.0)
    t_a, _, _ = s.build(segs, OUT / "final_output.mp3", False, False, 1.0, ["-c:a", "libmp3lame", "-b:a", "192k"], pad=1.0)
    print(f"SUMMARY download {t_dl:.1f}s + video render {t_v:.1f}s + audio render {t_a:.1f}s "
          f"= {t_dl + t_v + t_a:.1f}s total, output {exp:.1f}s")
