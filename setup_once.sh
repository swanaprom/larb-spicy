#!/bin/sh
# setup_once: prepares everything this program needs, inside the .venv folder (SPEC §16).
# This file only finds a suitable Python; tools/env_setup.py does the rest.
# Safe to run again: nothing is rebuilt unless something is missing or out of range.
. "$(dirname "$0")/tools/find_python.sh"
larb_find_python || exit 1
exec "$LARB_PY" "$(dirname "$0")/tools/env_setup.py" setup
