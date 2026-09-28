# Sourced by setup_once.sh and run.sh (not run on its own).
# larb_find_python sets LARB_PY to a Python in the supported range (python-range.txt).
# None found: on Mac, offers to install the newest version in the range with Homebrew (only
# after a yes); on Linux, prints the install command (never sudo). Returns 1 then.
# Everything after this is tools/env_setup.py (SPEC §16).
#
# For testing, the environment variable LARB_PYTHON_RANGE (e.g. 3.9-3.9) overrides the file.

larb_find_python() {
    root=$(cd "$(dirname "$0")" && pwd)
    range=${LARB_PYTHON_RANGE:-$(head -n 1 "$root/python-range.txt")}
    range=$(printf '%s' "$range" | tr -d ' \r')
    low_part=${range%-*}; high_part=${range#*-}
    major=${low_part%%.*}; low=${low_part#*.}; high=${high_part#*.}
    case "$major$low$high" in
        ''|*[!0-9]*) echo "python-range.txt should contain a range like 3.11-3.13, not \"$range\"."; return 1 ;;
    esac

    # 1. python3.13, python3.12, ... (newest first), as the distributions and Homebrew name them.
    minor=$high
    while [ "$minor" -ge "$low" ]; do
        candidate=$(command -v "python$major.$minor" 2>/dev/null)
        if [ -n "$candidate" ] && "$candidate" -c 'import sys' >/dev/null 2>&1; then
            LARB_PY=$candidate
            return 0
        fi
        minor=$((minor - 1))
    done

    # 2. python3, if it's in the range and not a venv (the venv may get rebuilt).
    for name in "python$major" python; do
        candidate=$(command -v "$name" 2>/dev/null) || continue
        if "$candidate" -c "import sys; v = sys.version_info[:2]; sys.exit(not ((($major, $low) <= v <= ($major, $high)) and sys.prefix == sys.base_prefix))" >/dev/null 2>&1; then
            LARB_PY=$candidate
            return 0
        fi
    done

    # 3. None: the newest version in the range.
    want="$major.$high"
    echo
    echo "No Python $major.$low to $major.$high was found on this computer."
    echo "This program needs Python $want. It installs alongside any other Python you have,"
    echo "so nothing needs to be uninstalled."
    if [ "$(uname -s)" = "Darwin" ]; then
        if command -v brew >/dev/null 2>&1; then
            printf 'Install Python %s now with Homebrew (brew install python@%s)? [y/N] ' "$want" "$want"
            read -r answer || answer=""
            case "$answer" in
                y|Y|yes|YES|Yes)
                    if brew install "python@$want"; then
                        echo
                        echo "Python $want is installed. Open a new terminal and run ./setup_once.sh again."
                        return 1
                    fi
                    echo "Homebrew couldn't install it." ;;
            esac
        fi
        echo
        echo "Get Python $want for macOS from https://www.python.org/downloads/ and run the installer."
        echo "Then open a new terminal and run ./setup_once.sh again."
        return 1
    fi

    # Linux: print the command, never run sudo ourselves.
    echo
    echo "Install it with your package manager, then run ./setup_once.sh again:"
    if command -v apt-get >/dev/null 2>&1; then
        echo "    sudo apt install python$want python$want-venv python$want-tk"
        echo "If apt can't find python$want (e.g. your Ubuntu has a newer Python), add the"
        echo "deadsnakes archive first, which provides older and newer Pythons for Ubuntu:"
        echo "    sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update"
    elif command -v dnf >/dev/null 2>&1; then
        echo "    sudo dnf install python$want python$want-tkinter"
    else
        echo "    (install the package for Python $want, plus its venv and tkinter parts)"
    fi
    return 1
}
