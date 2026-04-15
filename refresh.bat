@echo off
setlocal
cd /d "%~dp0"

echo [1/3] Syncing sessions from this machine...
python scripts\build_session_archive.py --sync
if errorlevel 1 ( echo ERROR: build failed & pause & exit /b 1 )

echo.
echo [2/3] Rebuilding unified index...
python scripts\merge_archives.py
if errorlevel 1 ( echo ERROR: merge failed & pause & exit /b 1 )

if not exist insights-narrative.json (
    echo.
    echo TIP: For AI-generated narrative insights, open this project in Claude Code
    echo      ^(or any LLM with file access^) and run /generate-insights
)

echo.
echo [3/3] Done. Opening archive...
start index.html

endlocal
