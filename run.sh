#!/bin/sh
# run: starts the program (SPEC §16). This file only finds a suitable Python;
# tools/env_setup.py checks the venv, updates yt-dlp, and starts the program.
#
#   ./run.sh "<sheet URL or CSV file>" [--countdown FILE_OR_URL] [--rows 2-10] [--verbose]
#
# Without arguments it asks for the sheet URL.
. "$(dirname "$0")/tools/find_python.sh"
larb_find_python || exit 1
exec "$LARB_PY" "$(dirname "$0")/tools/env_setup.py" run "$@"
