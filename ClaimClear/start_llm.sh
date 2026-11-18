#!/bin/sh
# Start a local LLM for ClaimClear and choose its model (macOS / Linux). Then run ./start.sh.
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then exec "$py" start_llm.py "$@"; fi
done
echo "Python is needed to start: install any Python 3 and run ./start_llm.sh again." >&2
exit 1
