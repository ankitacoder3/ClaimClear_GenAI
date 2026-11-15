#!/bin/sh
# ClaimClear in one command (macOS / Linux): installs on first run, starts the servers, opens the web UI.
# Any Python 3.8+ can start it; start.py picks or downloads a Python the dependencies support.
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then exec "$py" start.py "$@"; fi
done
echo "Python is needed to start: install any Python 3 and run ./start.sh again." >&2
exit 1
