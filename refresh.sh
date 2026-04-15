#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "[1/3] Syncing sessions from this machine..."
python3 scripts/build_session_archive.py --sync

echo
echo "[2/3] Rebuilding unified index..."
python3 scripts/merge_archives.py

if [ ! -f insights-narrative.json ]; then
    echo
    echo "TIP: For AI-generated narrative insights, open this project in Claude Code"
    echo "     (or any LLM with file access) and run /generate-insights"
fi

echo
echo "[3/3] Done. Opening archive..."
open index.html
