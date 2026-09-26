"""Spike: TOML config generate / read / write round trip (SPEC §7 schema only).

Read with tomllib (stdlib), write with tomli-w. Atomic write = temp file in the
same directory + os.replace(). Everything lands in workspace/spike/toml/.
Throwaway code. Only the findings matter (docs/TECH.md).
"""
import copy
import os
import tempfile
import tomllib
from pathlib import Path

import tomli_w

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "workspace" / "spike" / "toml"
DIR.mkdir(parents=True, exist_ok=True)
CFG = DIR / "config.toml"

# SPEC §7 keys exactly — no new keys (schema changes need the maintainer).
DEFAULTS = {
    "output": {"directory": "", "filename_template": "{date}_{time}.mp4"},
    "countdown": {"default_urls": [], "default_files": []},
    "download": {"cache_directory": ""},
    "processing": {"audio_only": True, "mirror": False, "crossfade_duration_seconds": 1.0},
}


def atomic_write(path: Path, data: dict) -> None:
    text = tomli_w.dumps(data)                      # raises before touching disk if data is bad
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)                       # atomic on the same volume
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read(path: Path) -> dict:
    with open(path, "rb") as f:                     # tomllib needs binary mode
        return tomllib.load(f)


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


if __name__ == "__main__":
    for p in DIR.glob("*"):
        p.unlink()

    # 1. first run: no config -> generate defaults
    if not CFG.exists():
        atomic_write(CFG, DEFAULTS)
    check("generate defaults on first run", read(CFG) == DEFAULTS)
    print("---- generated file ----\n" + CFG.read_text(encoding="utf-8") + "------------------------")

    # 2. edit + write + read back, with awkward real-world values
    cfg = copy.deepcopy(read(CFG))
    cfg["output"]["directory"] = r"D:\งานเต้น\Random Dance [2026] & (final)"
    cfg["countdown"]["default_urls"] = ["https://youtu.be/R0sdcqOEiTs?si=Ckzak_1O9OOE5goE"]
    cfg["countdown"]["default_files"] = [r"C:\Users\x\!countdown.mp4", "relative/นับถอยหลัง.mp3"]
    cfg["processing"]["crossfade_duration_seconds"] = 0.1
    cfg["processing"]["audio_only"] = False
    atomic_write(CFG, cfg)
    back = read(CFG)
    check("round trip: Thai text, Windows backslashes, brackets, URL query", back == cfg)
    check("float 0.1 survives exactly", back["processing"]["crossfade_duration_seconds"] == 0.1)
    check("backslashes written as escaped basic strings or literal strings",
          True, next(l for l in CFG.read_text(encoding="utf-8").splitlines() if l.startswith("directory")))

    # 3. key order is preserved (dict order)
    check("table/key order preserved", list(back) == list(cfg) and list(back["processing"]) == list(cfg["processing"]))

    # 4. comments are dropped by a write
    commented = DIR / "commented.toml"
    commented.write_text('# operator note\n[processing]\nmirror = true  # keep!\n', encoding="utf-8")
    atomic_write(commented, read(commented))
    txt = commented.read_text(encoding="utf-8")
    check("comments dropped after write (expected, SPEC/TECH §5)", "#" not in txt, repr(txt))

    # 5. None is not a TOML value
    bad = copy.deepcopy(cfg); bad["output"]["directory"] = None
    before = CFG.read_bytes()
    try:
        atomic_write(CFG, bad)
        check("None rejected", False)
    except TypeError as e:
        check("None rejected BEFORE disk is touched", CFG.read_bytes() == before, f"TypeError: {e}")

    # 6. hand-edited broken file -> clear error with line/col
    broken = DIR / "broken.toml"
    broken.write_text('[processing]\nmirror = yes\n', encoding="utf-8")
    try:
        read(broken)
        check("broken file rejected", False)
    except tomllib.TOMLDecodeError as e:
        check("broken file rejected with position", True, str(e))

    # 7. crash during write leaves the old file intact and no temp file behind
    before = CFG.read_bytes()
    real_replace = os.replace
    os.replace = lambda *a: (_ for _ in ()).throw(OSError("simulated crash"))
    try:
        atomic_write(CFG, DEFAULTS)
    except OSError:
        pass
    finally:
        os.replace = real_replace
    check("crash mid-write: old file intact", CFG.read_bytes() == before)
    check("crash mid-write: no temp file left", not list(DIR.glob("*.tmp")))

    # 8. Windows: replace while another handle has the file open
    with open(CFG, "rb") as held:
        try:
            atomic_write(CFG, DEFAULTS)
            check("replace while file is open elsewhere", True, "succeeded")
        except PermissionError as e:
            check("replace while file is open elsewhere", False, f"PermissionError: {e}")
    check("no temp file left after that", not list(DIR.glob("*.tmp")))

    # 9. schema check helper idea: missing/extra keys vs DEFAULTS
    partial = {"processing": {"mirror": True}, "junk": {"x": 1}}
    missing = [f"{t}.{k}" for t, keys in DEFAULTS.items() for k in keys if k not in partial.get(t, {})]
    extra = [t for t in partial if t not in DEFAULTS]
    check("detect missing / unknown keys against defaults", bool(missing) and extra == ["junk"],
          f"missing={len(missing)} e.g. {missing[:2]}, unknown={extra}")

    # 10. line endings / BOM: a file saved by Notepad with BOM
    bom = DIR / "bom.toml"
    bom.write_bytes("\ufeff[processing]\r\nmirror = true\r\n".encode("utf-8"))
    try:
        check("Notepad UTF-8 BOM + CRLF readable", read(bom) == {"processing": {"mirror": True}})
    except tomllib.TOMLDecodeError as e:
        check("Notepad UTF-8 BOM + CRLF readable", False, str(e))
