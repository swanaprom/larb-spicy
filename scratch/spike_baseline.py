"""Spike: render-time baseline, 10 songs x 37 s + countdowns, one pass."""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import spike_one_pass as s

dl = s.ROOT / "workspace" / "spike" / "dl"
vid = next(dl.glob(os.environ.get("VGLOB", "C_full_video.*"))); aud = next(dl.glob("A_full_audio.*"))
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
def segs(song, cd):
    out = []
    for i in range(N):
        st = 5.0 + i * 11.0          # stay inside the 162 s song
        out += [(cd, 0, None, True), (song, st, st + 37.0, False)]
    return out
print(f"cpu count {os.cpu_count()}, N={N}")
if not os.environ.get("VGLOB"): s.build(segs(aud, s.FIX / "countdown" / "!countdown.mp3"), s.OUT / f"base_audio_{N}.mp3",
        False, False, 1.0, ["-c:a", "libmp3lame", "-b:a", "192k"])
s.build(segs(vid, s.FIX / "countdown" / "!countdown.mp4"), s.OUT / f"base_video_{N}.mp4",
        True, True, 1.0, ["-c:a", "aac", "-b:a", "192k"])
