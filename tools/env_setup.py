"""Everything setup_once and run do once the shell script has found a suitable Python.

setup_once.bat/.sh and run.bat/.sh only find a Python in the supported range
(python-range.txt) and start this script with it (SPEC §16):

    <python> tools/env_setup.py setup
    <python> tools/env_setup.py run [program arguments...]

It is never started with the venv's own Python: it may delete and rebuild the venv, which
Windows refuses while that Python is running. Standard library only, since it runs before
the venv exists. It never installs anything outside .venv without asking first, and never
uses sudo: on Linux it prints the command instead.
"""

import hashlib
import importlib.util
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
RANGE_FILE = ROOT / "python-range.txt"
# Written after the pinned libraries installed; holds a hash of requirements.txt, so a
# changed requirements.txt (e.g. after a git pull) is installed again, and an unchanged one
# is skipped. That's what makes running setup again fast.
STAMP = VENV / "larb-installed.txt"
# For testing only (e.g. acceptance "no Python in range"): overrides python-range.txt.
RANGE_OVERRIDE = "LARB_PYTHON_RANGE"


class SetupError(Exception):
    """A problem the operator has to fix; the message says how."""


class RestartNeeded(SetupError):
    """Something was installed outside the venv; a new terminal is needed to see it."""


def say(message: str = "") -> None:
    print(message, flush=True)


def ask_yes(question: str) -> bool:
    """Ask a yes/no question. Enter, anything but y/yes, or no terminal = No."""
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        say()
        return False


# --- supported Python range --------------------------------------------------------------

def read_range() -> tuple[tuple[int, int], tuple[int, int]]:
    """The supported range, e.g. ((3, 11), (3, 13)), from python-range.txt (or the override)."""
    text = os.environ.get(RANGE_OVERRIDE) or RANGE_FILE.read_text(encoding="utf-8")
    match = re.search(r"(\d+)\.(\d+)\s*-\s*(\d+)\.(\d+)", text)
    if not match:
        raise SetupError(f"{RANGE_FILE.name} should contain a range like 3.11-3.13, not {text.strip()!r}")
    a, b, c, d = map(int, match.groups())
    return (a, b), (c, d)


def version_text(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


# --- the venv ----------------------------------------------------------------------------

def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def venv_env() -> dict[str, str]:
    """Environment for the venv's Python: the program's code on the path, UTF-8 output
    (so Thai titles print correctly on any console codepage, e.g. cp874)."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def venv_run(code: str, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a few lines of Python with the venv's Python (it has the libraries, we don't).
    Unbuffered (-u), so its lines appear in order with ours."""
    return subprocess.run([str(venv_python()), "-u", "-c", code], env=venv_env(), text=True,
                          capture_output=capture, encoding="utf-8" if capture else None,
                          errors="replace" if capture else None)


def pip(*args: str, quiet: bool = True) -> int:
    command = [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check"]
    return subprocess.call(command + (["-q"] if quiet else []) + list(args))


def venv_version() -> tuple[int, int] | None:
    """The venv's Python version, or None if there's no venv or its Python doesn't start
    (e.g. the Python it was built with has been uninstalled)."""
    if not venv_python().exists():
        return None
    try:
        result = subprocess.run([str(venv_python()), "-c", "import sys; print(*sys.version_info[:2])"],
                                capture_output=True, text=True, timeout=60)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    major, minor = result.stdout.split()
    return int(major), int(minor)


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def _remove_venv() -> None:
    def make_writable_and_retry(func, path, _error):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    # Python 3.12 renamed rmtree's error hook (the old name prints a deprecation warning).
    hook = "onexc" if sys.version_info >= (3, 12) else "onerror"
    try:
        shutil.rmtree(VENV, **{hook: make_writable_and_retry})
    except OSError as e:
        raise SetupError(f"Couldn't delete the old .venv folder ({e}).\n"
                         "Close anything that may be using it (another run window, a terminal "
                         "where it is activated, VS Code), then try again.") from e


def _check_venv_module() -> None:
    """Debian/Ubuntu ship Python without the part that builds venvs (ensurepip)."""
    if importlib.util.find_spec("ensurepip") is not None:
        return
    version = version_text(sys.version_info[:2])
    raise SetupError(f"This Python ({sys.executable}) can't build a venv: its 'venv' package is missing.\n"
                     f"Install it, then run setup again:\n    sudo apt install python{version}-venv")


def ensure_venv() -> bool:
    """Make sure .venv exists, uses a Python in the range, and has the pinned libraries.

    Returns True if anything was (re)built or installed.
    """
    low, high = read_range()
    current = venv_version()
    if current is None:
        reason = "missing" if not VENV.exists() else "broken (its Python doesn't start)"
    elif not low <= current <= high:
        reason = (f"built with Python {version_text(current)}, outside the supported "
                  f"{version_text(low)}-{version_text(high)}")
    else:
        reason = ""

    changed = False
    if reason:
        say(f"The .venv folder is {reason}: building it with Python "
            f"{version_text(sys.version_info[:2])} ({sys.executable}).")
        _check_venv_module()
        if VENV.exists():
            _remove_venv()
        if subprocess.call([sys.executable, "-m", "venv", str(VENV)]) != 0:
            raise SetupError("Building the venv failed (see the message above).")
        changed = True
    else:
        say(f"The .venv folder is fine (Python {version_text(current)}).")

    wanted = requirements_hash()
    if not STAMP.exists() or STAMP.read_text(encoding="utf-8").strip() != wanted:
        say("Installing the pinned libraries from requirements.txt (about a minute the first time)...")
        if pip("-r", str(REQUIREMENTS)) != 0:
            raise SetupError("Installing the libraries failed (see above). Check the internet "
                             "connection and run setup_once again.")
        STAMP.write_text(wanted + "\n", encoding="utf-8")
        changed = True
    else:
        say("The pinned libraries are already installed.")
    return changed


def update_yt_dlp() -> None:
    """yt-dlp is always the latest version (SPEC §16); it's never pinned.

    No internet: warn and keep the installed version. Not installed at all: stop.
    """
    def installed_version() -> str:
        found = venv_run("import yt_dlp.version as v; print(v.__version__)", capture=True)
        return found.stdout.strip() if found.returncode == 0 else ""

    before = installed_version()
    # pip install -U, not "yt-dlp -U" (that one is for the standalone yt-dlp program).
    # Short timeout and one retry, so a missing connection costs seconds, not minutes.
    command = [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-q",
               "--upgrade", "--retries", "1", "--timeout", "10", "yt-dlp"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    # When yt-dlp is already installed, pip exits with 0 even if it couldn't reach PyPI
    # (found 2026-09-28): only its warnings tell. Quiet (-q) and fine = no output at all.
    output = result.stdout + result.stderr
    offline = result.returncode != 0 or "Retrying" in output or "Could not fetch URL" in output
    installed = installed_version()
    if not offline:
        change = f", updated from {before}" if before and before != installed else ""
        say(f"yt-dlp {installed} (latest{change}).")
    elif installed:
        say(f"WARNING: couldn't update yt-dlp (no internet?). Continuing with the installed "
            f"version, {installed}.")
    else:
        say(output.strip())
        raise SetupError("yt-dlp isn't installed and couldn't be downloaded (see above). Check "
                         "the internet connection and try again.")


# --- FFmpeg ------------------------------------------------------------------------------

def _linux_package_manager() -> str:
    """'apt', 'dnf' or '' — only used to print the right install command."""
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8").lower()
    except OSError:
        return ""
    ids = " ".join(re.findall(r"^(?:id|id_like)=\"?([^\"\n]*)", release, re.MULTILINE))
    if any(name in ids for name in ("debian", "ubuntu")):
        return "apt"
    if any(name in ids for name in ("fedora", "rhel", "centos")):
        return "dnf"
    return ""


def _offer_ffmpeg_install() -> None:
    """No usable FFmpeg: ask before installing one (Windows/Mac), or print how (Linux)."""
    say()
    say("FFmpeg 7.1 or newer is needed. It installs system-wide, next to anything else you have.")
    if sys.platform == "win32":
        if shutil.which("winget") and ask_yes("Install FFmpeg now with winget (package Gyan.FFmpeg)?"):
            if subprocess.call(["winget", "install", "--id", "Gyan.FFmpeg", "-e"]) == 0:
                raise RestartNeeded("FFmpeg is installed. Close this window, open a new terminal, "
                                 "and run setup_once again.")
            say("winget couldn't install it.")
        raise SetupError("Get FFmpeg for Windows from https://www.gyan.dev/ffmpeg/builds/ "
                         "(the 'release essentials' build), add its bin folder to PATH, then "
                         "open a new terminal and run setup_once again.")
    if sys.platform == "darwin":
        if shutil.which("brew") and ask_yes("Install FFmpeg now with Homebrew (brew install ffmpeg)?"):
            if subprocess.call(["brew", "install", "ffmpeg"]) == 0:
                raise RestartNeeded("FFmpeg is installed. Open a new terminal and run ./setup_once.sh again.")
            say("Homebrew couldn't install it.")
        raise SetupError("Install FFmpeg (e.g. from https://brew.sh: brew install ffmpeg), then "
                         "open a new terminal and run ./setup_once.sh again.")
    command = {"apt": "sudo apt install ffmpeg", "dnf": "sudo dnf install ffmpeg"}.get(
        _linux_package_manager(), "install the 'ffmpeg' package with your package manager")
    raise SetupError(f"Install FFmpeg, then run ./setup_once.sh again:\n    {command}\n"
                     "WARNING: your distribution's FFmpeg may be older than 7.1 (check with "
                     "'ffmpeg -version'). If it is, it won't be used: get a newer build from "
                     "https://ffmpeg.org/download.html (Linux static builds) instead.")


# One line instead of a traceback when the download fails (e.g. no internet).
FETCH_STATIC = """
from larb.adapters.ffmpeg.locate import fetch_static
try:
    fetch_static()
except Exception as e:
    print(f"static-ffmpeg: {type(e).__name__}: {e}")
    raise SystemExit(1)
"""

FIND_FFMPEG = """
from larb.adapters.ffmpeg.locate import find_ffmpeg
from larb.core.errors import LarbError
try:
    tools = find_ffmpeg()
except LarbError as e:
    print(e)
    raise SystemExit(1)
print(f"FFmpeg {tools.version_text} ({tools.origin}): {tools.ffmpeg}")
"""


def ensure_ffmpeg(offer_install: bool) -> None:
    """Download static-ffmpeg into the venv (only setup does this, TECH §3), then check
    what the program will actually use: static-ffmpeg, else a system FFmpeg 7.1+."""
    # Does nothing (and prints nothing) when the binaries are already there.
    say("Checking FFmpeg (the first time this downloads about 200 MB, ~45 s)...")
    fetched = venv_run(FETCH_STATIC)
    if fetched.returncode != 0:
        say("WARNING: the static-ffmpeg download failed. Looking for a system FFmpeg 7.1 or "
            "newer instead.")
    found = venv_run(FIND_FFMPEG, capture=True)
    say(found.stdout.strip())
    if found.returncode == 0:
        return
    if offer_install:
        _offer_ffmpeg_install()
    raise SetupError("No usable FFmpeg. Run setup_once again.")


# --- tkinter -----------------------------------------------------------------------------

def check_tkinter() -> None:
    """The GUI needs tkinter, which some Pythons ship separately. Only reported, never
    installed: the command-line program works without it."""
    if venv_run("import tkinter", capture=True).returncode == 0:
        say("tkinter: available (needed by the GUI).")
        return
    version = version_text(sys.version_info[:2])
    if sys.platform == "darwin":
        how = f"brew install python-tk@{version}"
    elif sys.platform == "win32":
        how = "run the Python installer again, choose Modify, and tick 'tcl/tk and IDLE'"
    elif _linux_package_manager() == "apt":
        how = f"sudo apt install python{version}-tk"
    elif _linux_package_manager() == "dnf":
        how = f"sudo dnf install python{version}-tkinter"
    else:
        how = f"install the Tk package for Python {version} (often python3-tk)"
    say(f"WARNING: tkinter is missing. The command-line program works without it, but the GUI "
        f"will need it. To install it:\n    {how}")


# --- fonts (Linux) ---------------------------------------------------------------------

# Song titles are Thai, Korean and Japanese. Windows and Mac have fonts for all three; a
# minimal Linux (e.g. WSL Ubuntu) may have none, and the window then shows boxes.
FONT_LANGUAGES = {"th": "Thai", "ko": "Korean", "ja": "Japanese"}
FONT_PACKAGES = {"apt": "fonts-thai-tlwg fonts-noto-cjk",
                 "dnf": "google-noto-sans-thai-fonts google-noto-sans-cjk-fonts"}


def check_fonts() -> None:
    """Linux only: report missing fonts and how to install them (never installs: needs sudo)."""
    if not sys.platform.startswith("linux") or shutil.which("fc-list") is None:
        return
    missing = [name for lang, name in FONT_LANGUAGES.items()
               if not subprocess.run(["fc-list", f":lang={lang}", "family"], capture_output=True,
                                     text=True).stdout.strip()]
    if not missing:
        say("Fonts: Thai, Korean and Japanese available.")
        return
    packages = FONT_PACKAGES.get(_linux_package_manager())
    how = (f"sudo {_linux_package_manager()} install {packages}" if packages else
           "install Noto fonts for Thai and CJK (often fonts-thai-tlwg and fonts-noto-cjk)")
    say(f"WARNING: no font for {', '.join(missing)} text: song titles would show as boxes in the "
        f"window. To install them:\n    {how}")


# --- the two commands --------------------------------------------------------------------

def setup() -> int:
    start = time.monotonic()
    say(f"Setting up with Python {platform.python_version()} ({sys.executable})")
    ensure_venv()
    update_yt_dlp()
    ensure_ffmpeg(offer_install=True)
    check_tkinter()
    check_fonts()
    run_script = "run.bat" if sys.platform == "win32" else "./run.sh"
    say()
    say(f"Setup finished in {time.monotonic() - start:.0f} s. Next: {run_script} opens the window "
        f"(or {run_script} \"<sheet URL>\" for the terminal version).")
    return 0


def run(args: list[str]) -> int:
    low, high = read_range()
    current = venv_version()
    if current is None or not low <= current <= high:
        # Same steps as setup_once, without questions: a run never asks to install anything.
        # Said up front: minutes without a word would look like a freeze.
        say("Rebuilding the environment, including a one-time FFmpeg download (~200 MB). "
            "This can take a few minutes.")
        ensure_venv()
        ensure_ffmpeg(offer_install=False)
        check_tkinter()
        check_fonts()
    elif not STAMP.exists() or STAMP.read_text(encoding="utf-8").strip() != requirements_hash():
        # requirements.txt changed (e.g. after a git pull), or a rebuild was interrupted
        # before the libraries were installed: then FFmpeg was never downloaded either.
        ensure_venv()
        ensure_ffmpeg(offer_install=False)   # quick when the binaries are already there
    update_yt_dlp()

    if not args:
        # Started without arguments, e.g. double-clicked: open the window.
        if venv_run("import tkinter", capture=True).returncode != 0:
            check_tkinter()   # says how to install it
            run_script = "run.bat" if sys.platform == "win32" else "./run.sh"
            say(f"The window needs tkinter. The terminal version works without it: "
                f"{run_script} \"<sheet URL>\".")
            return 1
        say("Opening the window...")

    # No arguments: the window; with arguments: the terminal version (larb/__main__.py).
    return subprocess.call([str(venv_python()), "-m", "larb", *args], env=venv_env())


def main(argv: list[str]) -> int:
    if Path(sys.prefix).resolve() == VENV.resolve():
        say("tools/env_setup.py must be started by setup_once / run, not with the venv's own Python.")
        return 2
    if not argv or argv[0] not in ("setup", "run"):
        say(__doc__)
        return 2
    try:
        return setup() if argv[0] == "setup" else run(argv[1:])
    except RestartNeeded as e:
        say()
        say(str(e))
        return 1
    except SetupError as e:
        say()
        say(f"ERROR: {e}")
        return 1
    except KeyboardInterrupt:
        say()
        say("Stopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
