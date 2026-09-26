"""Spike edge cases: end_time past real file length; long graphs via script file."""
import sys, subprocess
sys.path.insert(0, "scratch")
import spike_one_pass as s

cd = s.FIX / "countdown" / "!countdown.mp4"
small = next(s.FIX.glob("*.mp4"))   # really 7.27 s long
# (a) ask for 1.0 -> 20.0 on a 7.27 s file, then a countdown after it
segs = [(small, 1.0, 20.0, False), (cd, 0, None, True)]
try:
    s.build(segs, s.OUT / "overrun.mp4", True, False, 1.0, ["-c:a", "aac"])
except SystemExit as e:
    print("FAILED:", e)

# (b) graph length for many songs: estimate chars per segment in the video graph
per_seg = 250 + len(str(small))
for n in (20, 50, 100, 400):
    print(f"{n} songs -> ~{2*n*per_seg} chars (Windows cmd limit 32767)")

# (c) does -/filter_complex <file> work in ffmpeg 8?
g = s.OUT / "graph.txt"
g.write_text("[0:a][1:a]acrossfade=d=1[aout]", encoding="utf-8")
cda = s.FIX / "countdown" / "!countdown.mp3"
s.ffrun(["-i", str(cda), "-i", str(cda), "-/filter_complex", str(g), "-map", "[aout]", str(s.OUT / "script.mp3")])
print("script-file graph OK, dur", s.duration(s.OUT / "script.mp3"))
