"""Spike: real 2-song render with +-1 s padding, and chunk-then-join ("sandwich").

Modes:
  real    two real sheet songs + countdowns, pad 1 s, audio and video
  edge    padding clamp at file start/end; overrun now refused
  chunk   N songs: one pass  vs  chunks of K rendered separately, then joined
          with the same crossfade at the seam
Throwaway code. Only the findings matter (docs/TECH.md).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spike_one_pass as s

DL2 = s.ROOT / "workspace" / "spike" / "dl2"
OUT = s.ROOT / "workspace" / "spike" / "v2"
OUT.mkdir(parents=True, exist_ok=True)
CD_V = s.FIX / "countdown" / "!countdown.mp4"
CD_A = s.FIX / "countdown" / "!countdown.mp3"
PERFECT = DL2 / "oKBwWQI-IoI.mp4"   # sheet row 2: 27-64
DRAMA = DL2 / "R0sdcqOEiTs.mp4"     # sheet row 3: 46-90
D = 1.0
AAC = ["-c:a", "aac", "-b:a", "192k"]
MP3 = ["-c:a", "libmp3lame", "-b:a", "192k"]


def real():
    songs = [(PERFECT, 27.0, 64.0), (DRAMA, 46.0, 90.0)]
    for video, cd, ext, codec in ((True, CD_V, "mp4", AAC), (False, CD_A, "mp3", MP3)):
        segs = []
        for p, a, b in songs:
            segs += [(cd, 0, None, True), (p, a, b, False)]
        s.build(segs, OUT / f"real_2songs_pad1.{ext}", video, True, D, codec, pad=1.0)


def edge():
    small = next(s.FIX.glob("*.mp4"))            # 7.274 s long
    # start=0 and end=real length: padding must clamp on both sides, not fail
    s.build([(CD_V, 0, None, True), (small, 0.0, 7.274, False), (CD_V, 0, None, True)],
            OUT / "edge_clamp.mp4", True, False, D, AAC, pad=1.0)
    try:
        s.build([(small, 1.0, 20.0, False)], OUT / "edge_overrun.mp4", True, False, D, AAC)
    except SystemExit as e:
        print("overrun refused as expected:", e)


def song_list(n, video):
    cd = CD_V if video else CD_A
    pool = [(PERFECT, 27.0, 64.0), (DRAMA, 46.0, 90.0)]
    segs = []
    for i in range(n):
        p, a, b = pool[i % 2]
        shift = (i // 2) * 20.0                  # vary ranges so repeats aren't identical
        segs += [(cd, 0, None, True), (p, a + shift, b + shift, False)]
    return segs


def chunk(n, k, video):
    ext, codec = ("mp4", AAC) if video else ("mp3", MP3)
    segs = song_list(n, video)
    print(f"\n== {n} songs, chunks of {k}, video={video}")
    t_one, exp_one, _ = s.build(segs, OUT / f"one_{n}.{ext}", video, True, D, codec, pad=1.0)

    per_chunk = 2 * k                             # countdown + song per song
    chunk_files, t_chunks = [], 0.0
    for c in range(0, len(segs), per_chunk):
        f = OUT / f"chunk_{n}_{c // per_chunk}.{ext}"
        t, _, _ = s.build(segs[c:c + per_chunk], f, video, True, D, codec, pad=1.0)
        chunk_files.append(f)
        t_chunks += t
    # Join: chunks are "countdown-like" (is_cd=True -> no pad, no second mirror)
    t_join, exp_join, _ = s.build([(f, 0, None, True) for f in chunk_files],
                                  OUT / f"joined_{n}.{ext}", video, False, D, codec)
    print(f"SUMMARY one-pass {t_one:.1f}s -> {exp_one:.3f}s | chunks {t_chunks:.1f}s + join {t_join:.1f}s "
          f"= {t_chunks + t_join:.1f}s -> {exp_join:.3f}s | length diff {exp_join - exp_one:+.3f}s")


def pcm(path: Path, t0: float, dur: float) -> list[int]:
    """Decode a window to mono s16 samples (48 kHz) for seam comparison."""
    import array, subprocess
    raw = subprocess.run([s.FFMPEG, "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", str(path),
                          "-ac", "1", "-ar", "48000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return array.array("h", raw).tolist()


def seam_report(one: Path, joined: Path, seam: float):
    a, b = pcm(one, seam - 0.5, 1.0), pcm(joined, seam - 0.5, 1.0)
    n = min(len(a), len(b))
    diff = [abs(a[i] - b[i]) for i in range(n)]
    sig = (sum(x * x for x in a[:n]) / n) ** 0.5
    err = (sum(x * x for x in diff) / n) ** 0.5
    longest_zero = run = 0
    for x in b[:n]:
        run = run + 1 if x == 0 else 0
        longest_zero = max(longest_zero, run)
    print(f"   seam @ {seam:.3f}s: signal RMS {sig:.0f}, diff RMS {err:.0f} ({100 * err / max(sig, 1):.1f}%), "
          f"longest digital-silence run {longest_zero} samples ({longest_zero / 48:.1f} ms)")


def copyjoin(n, k, video):
    """Split each chunk boundary in the MIDDLE of a countdown, render chunks,
    then glue with the concat demuxer and -c copy (no re-encode)."""
    ext, codec = ("mp4", AAC) if video else ("m4a", AAC)
    segs = song_list(n, video)
    print(f"\n== copy-join {n} songs, chunks of {k}, video={video}")
    t_one, exp_one, _ = s.build(segs, OUT / f"one_{n}.{ext}", video, True, D, codec, pad=1.0)

    cd = segs[0][0]
    half = s.duration(cd) / 2
    groups, per_chunk = [], 2 * k
    for c in range(0, len(segs), per_chunk):
        groups.append(list(segs[c:c + per_chunk]))
    # move a countdown half across each boundary: ...song][cd first half | cd second half][song...
    for g in range(1, len(groups)):
        assert groups[g][0][3], "chunk must start with a countdown"
        groups[g - 1].append((cd, 0.0, half, True))
        groups[g][0] = (cd, half, None, True)
    files, t_chunks, seams, acc = [], 0.0, [], 0.0
    for g, segs_g in enumerate(groups):
        f = OUT / f"cchunk_{n}_{g}.{ext}"
        t, exp, _ = s.build(segs_g, f, video, True, D, codec, pad=1.0)
        files.append(f); t_chunks += t; acc += exp; seams.append(acc)
    listing = OUT / f"concat_{n}.txt"
    listing.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
    joined = OUT / f"cjoined_{n}.{ext}"
    t_join = s.ffrun(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
                      "-movflags", "+faststart", str(joined)])
    got = float(s.probe(joined)["format"]["duration"])
    print(f"SUMMARY one-pass {t_one:.1f}s -> {exp_one:.3f}s | chunks {t_chunks:.1f}s + copy-join {t_join:.1f}s "
          f"= {t_chunks + t_join:.1f}s -> {got:.3f}s | length diff {got - exp_one:+.3f}s")
    for sm in seams[:-1]:
        seam_report(OUT / f"one_{n}.{ext}", joined, sm)
    # control: the same comparison at a point with no seam (mid-chunk)
    print("   control (no seam here):", end="")
    seam_report(OUT / f"one_{n}.{ext}", joined, seams[0] / 2)


def seg_len(seg, pad):
    p, a, b, is_cd = seg
    real = s.duration(p)
    b = real if b is None else b
    if pad and not is_cd:
        a, b = max(0.0, a - pad), min(real, b + pad)
    return b - a


def hybrid(n, k):
    """Video: chunks split mid-countdown ON A FRAME BOUNDARY, glued with -c copy.
    Audio: one single pass over all segments (cheap). Then mux."""
    import math
    segs = song_list(n, True)
    cd = segs[0][0]
    groups = [list(segs[c:c + 2 * k]) for c in range(0, len(segs), 2 * k)]
    for g in range(1, len(groups)):
        body = sum(seg_len(x, 1.0) for x in groups[g - 1]) - D * (len(groups[g - 1]) - 1)
        # chunk length = body + split - D  must be a whole number of frames
        split = math.ceil((body + s.duration(cd) / 2 - D) * s.FPS) / s.FPS - body + D
        groups[g - 1].append((cd, 0.0, split, True))
        groups[g][0] = (cd, split, None, True)
    print(f"\n== hybrid {n} songs, chunks of {k}")
    files, t_v = [], 0.0
    for g, gs in enumerate(groups):
        f = OUT / f"hchunk_{n}_{g}.mp4"
        t, exp, _ = s.build(gs, f, True, True, D, AAC, pad=1.0)
        print(f"   chunk {g}: expected {exp:.4f}s = {exp * s.FPS:.2f} frames")
        files.append(f); t_v += t
    listing = OUT / f"hconcat_{n}.txt"
    listing.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
    vid = OUT / f"hvideo_{n}.mp4"
    t_cat = s.ffrun(["-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0:v", "-c", "copy", str(vid)])
    aud = OUT / f"haudio_{n}.m4a"
    t_a, exp_a, _ = s.build(segs, aud, False, False, D, AAC, pad=1.0)
    final = OUT / f"hybrid_{n}.mp4"
    t_mux = s.ffrun(["-i", str(vid), "-i", str(aud), "-map", "0:v", "-map", "1:a", "-c", "copy",
                     "-movflags", "+faststart", str(final)])
    info = s.probe(final)
    print(f"SUMMARY video chunks {t_v:.1f}s + concat {t_cat:.1f}s + audio pass {t_a:.1f}s + mux {t_mux:.1f}s "
          f"= {t_v + t_cat + t_a + t_mux:.1f}s ; expected {exp_a:.3f}s ;",
          {x["codec_type"]: x.get("duration") for x in info["streams"]})


if __name__ == "__main__":
    if sys.argv[1] == "hybrid":
        hybrid(int(sys.argv[2]), int(sys.argv[3]))
        raise SystemExit
    if sys.argv[1] == "copyjoin":
        copyjoin(int(sys.argv[2]), int(sys.argv[3]), "video" in sys.argv)
        raise SystemExit
    mode = sys.argv[1]
    if mode == "real":
        real()
    elif mode == "edge":
        edge()
    elif mode == "chunk":
        n, k = int(sys.argv[2]), int(sys.argv[3])
        chunk(n, k, "video" in sys.argv)
