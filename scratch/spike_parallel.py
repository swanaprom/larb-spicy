"""Spike: does downloading several songs at once help? 1 vs 2 vs 5 workers.

Same 5 rows as the moviepy comparison. Each run starts from an empty folder.
Per run: wall time, total MB, per-song time, errors. No JS runtime (maintainer decision).
Throwaway code. Only the findings matter (docs/TECH.md).
"""
import concurrent.futures
import csv
import shutil
import sys
import time
from pathlib import Path

import yt_dlp

sys.path.insert(0, str(Path(__file__).parent))
import spike_one_pass as s

CSV = s.ROOT / "workspace" / "spike" / "moviepy" / "data" / "entry.csv"
BASE = s.ROOT / "workspace" / "spike" / "par"
FORMATS = {
    "video": {"format_sort": ["vcodec:h264", "res:720", "acodec:m4a"]},
    "audio": {"format": "ba/b"},
}


def fetch(url: str, outdir: Path, kind: str):
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
            "ffmpeg_location": str(Path(s.FFMPEG).parent),
            "outtmpl": str(outdir / "%(id)s.%(ext)s"), **FORMATS[kind]}
    t0 = time.perf_counter()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        path = Path(info["requested_downloads"][0]["filepath"])
        return url, time.perf_counter() - t0, path.stat().st_size, None
    except Exception as e:  # spike: record, don't stop
        return url, time.perf_counter() - t0, 0, str(e)[:120]


def run(urls, workers: int, kind: str, tag: str):
    outdir = BASE / f"{kind}_{tag}"
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True)
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda u: fetch(u, outdir, kind), urls))
    wall = time.perf_counter() - t0
    mb = sum(r[2] for r in results) / 1e6
    per = " ".join(f"{r[1]:5.1f}" for r in results)
    errs = [r[3] for r in results if r[3]]
    print(f"SUMMARY {kind:5s} {tag:10s} workers={workers}  wall {wall:6.1f}s  {mb:6.1f} MB  "
          f"{mb / wall:5.2f} MB/s  per-song [{per}]  errors={len(errs)} {errs}", flush=True)
    shutil.rmtree(outdir, ignore_errors=True)   # next run must not find cached files


if __name__ == "__main__":
    with open(CSV, encoding="utf-8", newline="") as f:
        urls = [r[9] for r in list(csv.reader(f))[1:]]
    for w, tag in ((1, "seq"), (2, "par2"), (5, "par5"), (1, "seq-again")):
        run(urls, w, "video", tag)
    for w, tag in ((1, "seq"), (2, "par2"), (5, "par5")):
        run(urls, w, "audio", tag)
