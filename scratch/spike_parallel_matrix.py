"""Spike: average seconds per song vs number of parallel downloads (1..5).

12 songs (divisible by 1, 2, 3, 4 -> no lopsided last round; 5 has a tail).
Runs interleaved (1,2,3,4,5, 1,2,3,4,5, ...) so network drift spreads evenly.
Each failed song is retried once; first-try failures are counted separately.
No JS runtime (maintainer decision). Results also saved to workspace/spike/par/matrix.csv.
Throwaway code. Only the findings matter (docs/TECH.md).
"""
import concurrent.futures
import csv
import shutil
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spike_parallel as p

N_SONGS = 12
REPS = {"video": 2, "audio": 3}
WORKERS = [1, 2, 3, 4, 5]
RESULTS = p.BASE / "matrix.csv"


def one_run(urls, workers, kind, tag):
    outdir = p.BASE / f"m_{kind}_{tag}"
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True)

    def job(url):
        r = p.fetch(url, outdir, kind)
        first_err = r[3]
        if first_err:  # one retry with fresh metadata
            r2 = p.fetch(url, outdir, kind)
            r = (url, r[1] + r2[1], r2[2], r2[3])
        return r, first_err

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(job, urls))
    wall = time.perf_counter() - t0
    shutil.rmtree(outdir, ignore_errors=True)
    first_fail = [e for _, e in res if e]
    final_fail = [r[3] for r, _ in res if r[3]]
    mb = sum(r[2] for r, _ in res) / 1e6
    each = [r[1] for r, _ in res]
    row = dict(kind=kind, workers=workers, tag=tag, wall=round(wall, 1),
               per_song=round(wall / len(urls), 2), mean_each=round(statistics.mean(each), 1),
               mb=round(mb, 1), mbps=round(mb / wall, 2),
               first_try_fail=len(first_fail), final_fail=len(final_fail),
               errors=" | ".join(sorted({e[:70] for e in first_fail})))
    print("RUN", row, flush=True)
    return row


if __name__ == "__main__":
    with open(p.s.ROOT / "workspace" / "moviepy_table" / "entry.csv", encoding="utf-8", newline="") as f:
        urls = [r[9] for r in list(csv.reader(f))[1:N_SONGS + 1]]
    assert len(urls) == N_SONGS and all(urls)
    rows = []
    for kind in ("video", "audio"):
        for rep in range(1, REPS[kind] + 1):
            for w in WORKERS:
                rows.append(one_run(urls, w, kind, f"w{w}r{rep}"))
                with open(RESULTS, "w", encoding="utf-8", newline="") as f:
                    wr = csv.DictWriter(f, fieldnames=list(rows[0]))
                    wr.writeheader(); wr.writerows(rows)
    print("\nSUMMARY (mean over reps)")
    for kind in ("video", "audio"):
        base = None
        for w in WORKERS:
            rs = [r for r in rows if r["kind"] == kind and r["workers"] == w]
            ps = statistics.mean(r["per_song"] for r in rs)
            base = base or ps
            print(f"  {kind:5s} workers={w}: {ps:5.2f} s/song (runs: {[r['per_song'] for r in rs]}), "
                  f"{statistics.mean(r['mbps'] for r in rs):4.2f} MB/s, speedup x{base / ps:.2f}, "
                  f"first-try fails {sum(r['first_try_fail'] for r in rs)}, final fails {sum(r['final_fail'] for r in rs)}")
