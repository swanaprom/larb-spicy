"""Spike: audio normalization so songs and countdowns play at an even volume.

Modes (applied per segment, inside the one-pass graph):
  none       as-is
  peak       gain so each clip's peak hits -1 dBFS (what moviepy AudioNormalize does)
  dyn        loudnorm single pass (EBU R128, dynamic)
  twopass    measure each clip first, then loudnorm linear=true (one fixed gain per clip)
Scored by the loudness (LUFS) of each segment's middle in the OUTPUT: smaller spread = more even.
Throwaway code. Only the findings matter (docs/TECH.md).
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spike_one_pass as s

OUT = s.ROOT / "workspace" / "spike" / "norm"
OUT.mkdir(parents=True, exist_ok=True)
DL2 = s.ROOT / "workspace" / "spike" / "dl2"
CD = s.FIX / "countdown" / "!countdown.mp3"
TARGET = "I=-14:TP=-1.5:LRA=11"
D = 1.0
SEGS = [(CD, 0, None, True), (DL2 / "oKBwWQI-IoI.mp4", 27.0, 64.0, False),
        (CD, 0, None, True), (DL2 / "R0sdcqOEiTs.mp4", 46.0, 90.0, False),
        (CD, 0, None, True), (s.FIX / "XG - GRL GVNG (Instrumental).mp3", 30.0, 60.0, False),
        (CD, 0, None, True), (s.FIX / "sewer. [Instrumental].mp3", 10.0, 40.0, False)]


def ff_stderr(args):
    p = subprocess.run([s.FFMPEG, "-hide_banner", "-nostats", *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return p.stderr


def measure(path, start, dur):
    """loudnorm analysis pass -> dict with input_i, input_tp, input_lra, input_thresh, target_offset."""
    err = ff_stderr(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path),
                     "-af", f"loudnorm={TARGET}:print_format=json", "-f", "null", "-"])
    return json.loads(err[err.rindex("{"):err.rindex("}") + 1])


def peak_db(path, start, dur):
    err = ff_stderr(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path),
                     "-af", "volumedetect", "-f", "null", "-"])
    return float(re.search(r"max_volume: (-?[\d.]+) dB", err).group(1))


def make_norm(mode, t_measure):
    def norm(i, path, start, dur):
        if mode == "none":
            return ""
        if mode == "dyn":
            return f"loudnorm={TARGET}"
        t0 = time.perf_counter()
        if mode == "peak":
            f = f"volume={-1.0 - peak_db(path, start, dur):.2f}dB"
        else:  # twopass
            m = measure(path, start, dur)
            f = (f"loudnorm={TARGET}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                 f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                 f":offset={m['target_offset']}:linear=true")
        t_measure[0] += time.perf_counter() - t0
        return f
    return norm


def score(out, durs):
    """LUFS of each segment's middle (crossfade regions excluded)."""
    res, t = [], 0.0
    for i, dur in enumerate(durs):
        a, b = t + D, t + dur - D
        res.append(float(measure(out, a, b - a)["input_i"]))
        t += dur - D
    return res


if __name__ == "__main__":
    names = ["cd", "PerfectNight", "cd", "Drama", "cd", "XG", "cd", "sewer"]
    for mode in sys.argv[1:] or ["none", "peak", "dyn", "twopass"]:
        t_m = [0.0]
        out = OUT / f"norm_{mode}.mp3"
        dt, _, durs = s.build(SEGS, out, False, False, D, ["-c:a", "libmp3lame", "-b:a", "192k"],
                              pad=1.0, anorm=make_norm(mode, t_m))
        lufs = score(out, durs)
        print(f"SUMMARY {mode:8s} render {dt:5.1f}s + measure {t_m[0]:4.1f}s | "
              + " ".join(f"{n}={v:6.1f}" for n, v in zip(names, lufs))
              + f" | spread {max(lufs) - min(lufs):4.1f} LU")
