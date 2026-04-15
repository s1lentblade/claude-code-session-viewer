#!/usr/bin/env python3
"""
create_demo.py — Generate example-index.html from fictional demo session data.

Everything demo-related lives under demo/ so it never touches the real
RAWEVERYTHING/, Windows/, macOS/, or index.html used by the normal workflow.

Run from the repo root:
    python demo/create_demo.py

Outputs:
    demo/RAWEVERYTHING/Windows/projects/...   fictional Windows sessions (JSONL)
    demo/RAWEVERYTHING/macOS/projects/...     fictional macOS sessions (JSONL)
    demo/Windows/archive/                     built per-session HTML + index
    demo/macOS/archive/                       built per-session HTML + index
    example-index.html                        merged dark-mode demo index
"""

import importlib.util
import json
import random
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = Path(__file__).resolve().parent   # this script now lives inside demo/


# ---------------------------------------------------------------------------
# Fake session definitions — 100% fictional, no real user data
# ---------------------------------------------------------------------------

def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def make_usage(inp: int, out: int, cw: int = 0, cr: int = 0) -> dict:
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_input_tokens": cw,
        "cache_read_input_tokens": cr,
    }


def tool_use_block(name: str, tool_id: str, inp: dict) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": inp}


def tool_result_block(tool_id: str, content: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_id, "content": content}


# Deterministic entry UUIDs — uuid5 seeded from session_id + per-session counter
# so re-running create_demo.py produces byte-identical JSONL with no git churn.
_ENTRY_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_URL
_entry_counter: dict[str, int] = {}


def _entry_uuid(session_id: str) -> str:
    _entry_counter[session_id] = _entry_counter.get(session_id, 0) + 1
    return str(uuid.uuid5(_ENTRY_NS, f"{session_id}:{_entry_counter[session_id]}"))


def user_entry(session_id: str, dt: datetime, text: str) -> dict:
    return {
        "type": "user",
        "uuid": _entry_uuid(session_id),
        "timestamp": ts(dt),
        "sessionId": session_id,
        "message": {"role": "user", "content": text},
    }


def tool_result_entry(session_id: str, dt: datetime, tool_id: str, content: str) -> dict:
    return {
        "type": "user",
        "uuid": _entry_uuid(session_id),
        "timestamp": ts(dt),
        "sessionId": session_id,
        "message": {
            "role": "user",
            "content": [tool_result_block(tool_id, content)],
        },
    }


def asst_entry(session_id: str, dt: datetime, text: str, model: str, usage: dict,
               tools: list | None = None) -> dict:
    content: list = []
    if text:
        content.append({"type": "text", "text": text})
    if tools:
        content.extend(tools)
    return {
        "type": "assistant",
        "uuid": _entry_uuid(session_id),
        "timestamp": ts(dt),
        "sessionId": session_id,
        "message": {
            "role": "assistant",
            "content": content,
            "model": model,
            "usage": usage,
        },
    }


def perm_entry(session_id: str, dt: datetime) -> dict:
    return {
        "type": "permission-mode",
        "sessionId": session_id,
        "timestamp": ts(dt),
    }


# ---------------------------------------------------------------------------
# Fictional session content
# ---------------------------------------------------------------------------

SONNET = "claude-sonnet-4-5"
OPUS   = "claude-opus-4-5"
HAIKU  = "claude-haiku-4-5"

# Stable session IDs — one named constant per session so inserting or reordering
# sessions never shifts IDs of unrelated sessions (unlike the old iterator approach).
SID_RECIPE_1  = "57b9f56c-6dc4-4156-9ddc-ffad7acdc138"
SID_RECIPE_2  = "7c836cc5-b997-484c-9c5e-89d0f8e4f539"
SID_RECIPE_3  = "c3138d27-6f03-4cc4-a5f8-98e561b737ed"
SID_BUDGET_1  = "090d837a-62ce-4c6c-a378-9c5c4c7cf2de"
SID_BUDGET_2  = "7dfd855e-8bc5-462e-b515-ee6551acd385"
SID_BUDGET_3  = "f5470a3c-c30d-43e3-8625-2194416897f4"
SID_WORKOUT_1 = "1d41c3af-68d9-483e-ae6e-16479929c07d"
SID_WORKOUT_2 = "5b1beec3-9596-45a6-a7b7-e3d255ebfbff"
SID_WORKOUT_3 = "de6420f2-d859-41f9-82a5-cc215413526f"
SID_PHOTO_1   = "3fbc8c71-2204-4cff-b04f-751cad38d7ff"
SID_PHOTO_2   = "8a2298f1-f25f-4402-b659-3819c8305238"
SID_PHOTO_3   = "91bab398-6ef9-439b-8a98-cb7014e73f5e"
SID_PHOTO_4   = "9faffb46-0e47-436f-a7c5-2bf5c9a7d0b7"
SID_RUST_1    = "7578a4b7-1ae9-4175-80f1-e69c91a8eaf3"
SID_RUST_2    = "7cf3cea2-1852-4399-9950-4fc78db3be18"
SID_RUST_3    = "caad9c1b-a8a0-4dd3-96c1-12b01562d554"
SID_WRITING_1 = "00f915e9-7630-43c1-8f51-3e7057a1701f"
SID_WRITING_2 = "432f8fd6-ac60-4889-b376-c932c8a7bb7e"
SID_WRITING_3 = "616a1568-82d4-40ec-a82f-91096e4298a0"

def session_recipe_1(base: datetime) -> list[dict]:
    sid = SID_RECIPE_1
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "I want to build a command-line recipe manager in Python that stores recipes in SQLite. "
        "Each recipe has a name, ingredients list with quantities, instructions, and tags. "
        "Help me design the database schema and the initial CLI structure."))

    t += timedelta(seconds=8)
    tid1 = "tool_abc1"
    entries.append(asst_entry(sid, t,
        "Great project! Here's a clean SQLite schema and CLI skeleton using argparse.",
        SONNET, make_usage(1240, 820),
        tools=[tool_use_block("Write", tid1, {"file_path": "recipe_manager/schema.sql",
            "content": "CREATE TABLE recipes (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, ...);"})]))

    t += timedelta(seconds=3)
    entries.append(tool_result_entry(sid, t, tid1, "File written."))

    t += timedelta(seconds=6)
    tid2 = "tool_abc2"
    entries.append(asst_entry(sid, t,
        "Schema created. Now here's the main CLI entry point with subcommands for add, list, and show.",
        SONNET, make_usage(880, 1100, cw=3200),
        tools=[tool_use_block("Write", tid2, {"file_path": "recipe_manager/cli.py",
            "content": "import argparse\nimport sqlite3\n..."})]))

    t += timedelta(seconds=3)
    entries.append(tool_result_entry(sid, t, tid2, "File written."))

    t += timedelta(seconds=4)
    entries.append(user_entry(sid, t,
        "Can you add a search command that filters by ingredient name?"))

    t += timedelta(seconds=9)
    tid3 = "tool_abc3"
    entries.append(asst_entry(sid, t,
        "Sure — I'll add a `search` subcommand that does a LIKE query across the ingredients JSON column.",
        SONNET, make_usage(2100, 640, cr=3200),
        tools=[tool_use_block("Edit", tid3, {"file_path": "recipe_manager/cli.py",
            "old_string": "# search placeholder",
            "new_string": "parser_search = subparsers.add_parser('search')..."})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid3, "Edit applied."))

    t += timedelta(seconds=5)
    entries.append(asst_entry(sid, t,
        "Done. Run `python cli.py search chicken` to find all recipes containing chicken.",
        SONNET, make_usage(460, 220, cr=3200)))

    return entries


def session_recipe_2(base: datetime) -> list[dict]:
    sid = SID_RECIPE_2
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "Add ingredient quantity scaling to the recipe manager. "
        "If a recipe serves 4 and I want to serve 6, it should multiply all quantities automatically."))

    t += timedelta(seconds=7)
    tid1 = "tool_d1"
    entries.append(asst_entry(sid, t,
        "I'll add a `--servings` flag to the `show` command that scales quantities proportionally.",
        SONNET, make_usage(1800, 560),
        tools=[tool_use_block("Read", tid1, {"file_path": "recipe_manager/cli.py"})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "# cli.py content..."))

    t += timedelta(seconds=8)
    tid2 = "tool_d2"
    entries.append(asst_entry(sid, t,
        "Here's the scaling logic — it parses quantity strings like '1/2 cup' and '2 tbsp' using fractions.",
        SONNET, make_usage(2400, 980, cw=4100),
        tools=[tool_use_block("Edit", tid2, {"file_path": "recipe_manager/cli.py",
            "old_string": "def show_recipe(name):",
            "new_string": "def show_recipe(name, servings=None):"})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid2, "Edit applied."))

    t += timedelta(seconds=5)
    entries.append(asst_entry(sid, t,
        "The scaler handles fractions, decimals, and mixed numbers. "
        "Try: `python cli.py show 'Banana Bread' --servings 12`",
        SONNET, make_usage(580, 190, cr=4100)))

    return entries


def session_recipe_3(base: datetime) -> list[dict]:
    sid = SID_RECIPE_3
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "I want to export a recipe to a clean printable HTML file with nice typography. "
        "Nothing fancy — just something I can print from the browser without clutter."))

    t += timedelta(seconds=9)
    tid1 = "tool_e1"
    entries.append(asst_entry(sid, t,
        "I'll generate a self-contained HTML with embedded CSS — no external dependencies, "
        "print-optimised with @media print rules.",
        SONNET, make_usage(1100, 760),
        tools=[tool_use_block("Write", tid1, {"file_path": "recipe_manager/export_html.py",
            "content": "HTML_TEMPLATE = '''<!DOCTYPE html>...'''"})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "File written."))

    t += timedelta(seconds=5)
    entries.append(asst_entry(sid, t,
        "Run `python cli.py export 'Banana Bread' --out banana-bread.html` and open in any browser.",
        SONNET, make_usage(540, 180, cr=2800)))

    return entries


def session_budget_1(base: datetime) -> list[dict]:
    sid = SID_BUDGET_1
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "My bank exports transactions as CSV with columns: Date, Description, Amount, Balance. "
        "Help me write a Python script that parses these and categorises them automatically "
        "(groceries, dining, utilities, etc.) using keyword matching."))

    t += timedelta(seconds=10)
    tid1 = "tool_f1"
    entries.append(asst_entry(sid, t,
        "Here's a categoriser with a keyword map you can extend. "
        "It reads the CSV, applies rules in order, and writes a categorised CSV.",
        SONNET, make_usage(1650, 1040),
        tools=[tool_use_block("Write", tid1, {"file_path": "budget/categorise.py",
            "content": "CATEGORIES = {'groceries': ['tesco','waitrose','lidl'],...}"})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "File written."))

    t += timedelta(seconds=4)
    entries.append(user_entry(sid, t,
        "The date column uses DD/MM/YYYY format but Python's default csv reader "
        "is treating them as strings. How do I parse them properly?"))

    t += timedelta(seconds=6)
    entries.append(asst_entry(sid, t,
        "Use `datetime.strptime(row['Date'], '%d/%m/%Y')` — I'll update the parser now.",
        SONNET, make_usage(2200, 380, cr=2800)))

    return entries


def session_budget_2(base: datetime) -> list[dict]:
    sid = SID_BUDGET_2
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "Add monthly spending summary charts using matplotlib. "
        "I want a bar chart per category and a pie chart of total allocation."))

    t += timedelta(seconds=11)
    tid1 = "tool_g1"
    entries.append(asst_entry(sid, t,
        "I'll add a `charts.py` module. It groups transactions by month and category, "
        "then renders side-by-side subplots with a clean style.",
        OPUS, make_usage(2400, 1380, cw=6200),
        tools=[tool_use_block("Write", tid1, {"file_path": "budget/charts.py",
            "content": "import matplotlib.pyplot as plt\nimport pandas as pd\n..."})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "File written."))

    t += timedelta(seconds=7)
    tid2 = "tool_g2"
    entries.append(asst_entry(sid, t,
        "Charts generated. Run `python charts.py transactions_categorised.csv` "
        "and it saves `spending_summary.png` alongside the CSV.",
        OPUS, make_usage(860, 240, cr=6200),
        tools=[tool_use_block("Bash", tid2, {"command": "python budget/charts.py --help"})]))

    t += timedelta(seconds=3)
    entries.append(tool_result_entry(sid, t, tid2,
        "usage: charts.py [-h] [--out OUT] csv_file"))

    t += timedelta(seconds=4)
    entries.append(asst_entry(sid, t,
        "Working as expected. The `--out` flag lets you choose the output image path.",
        OPUS, make_usage(420, 110, cr=6200)))

    return entries


def session_budget_3(base: datetime) -> list[dict]:
    sid = SID_BUDGET_3
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "Some transactions at midnight are being grouped into the wrong month "
        "because the date parser ignores my local timezone (Europe/London). How do I fix this?"))

    t += timedelta(seconds=8)
    entries.append(asst_entry(sid, t,
        "The fix is to use `pytz` or Python 3.9+ `zoneinfo` to localise the naive datetime "
        "before grouping by month. Here's the corrected `parse_date()` function.",
        SONNET, make_usage(1900, 620)))

    t += timedelta(seconds=5)
    entries.append(user_entry(sid, t, "That fixed it — thank you!"))

    t += timedelta(seconds=3)
    entries.append(asst_entry(sid, t,
        "Great. If you're in a DST region, `zoneinfo.ZoneInfo('Europe/London')` handles "
        "the summer/winter transition automatically.",
        SONNET, make_usage(680, 140, cr=1800)))

    return entries


def session_workout_1(base: datetime) -> list[dict]:
    sid = SID_WORKOUT_1
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "Design a SQLite schema for a workout tracker. "
        "I want to log exercises (name, sets, reps, weight), "
        "group them into sessions, and track bodyweight separately."))

    t += timedelta(seconds=9)
    tid1 = "tool_h1"
    entries.append(asst_entry(sid, t,
        "Here's a normalised schema with a `workouts` table, `exercises` lookup, "
        "`sets` fact table, and a `bodyweight` log.",
        SONNET, make_usage(1400, 900),
        tools=[tool_use_block("Write", tid1, {"file_path": "workout/schema.sql",
            "content": "CREATE TABLE workouts (id INTEGER PRIMARY KEY, date TEXT, notes TEXT);\n..."})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "File written."))

    t += timedelta(seconds=5)
    entries.append(asst_entry(sid, t,
        "The schema includes a `volume` generated column (sets × reps × weight) for easy querying.",
        SONNET, make_usage(540, 160, cr=2600)))

    return entries


def session_workout_2(base: datetime) -> list[dict]:
    sid = SID_WORKOUT_2
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "Build the CLI interface for logging a workout session. "
        "I want to type `python log.py` and be prompted interactively for each exercise."))

    t += timedelta(seconds=12)
    tid1 = "tool_i1"
    entries.append(asst_entry(sid, t,
        "I'll build an interactive prompt loop using the `questionary` library for a nice UX.",
        OPUS, make_usage(2800, 1620, cw=7400),
        tools=[tool_use_block("Write", tid1, {"file_path": "workout/log.py",
            "content": "import questionary\nimport sqlite3\n..."})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "File written."))

    t += timedelta(seconds=6)
    tid2 = "tool_i2"
    entries.append(asst_entry(sid, t,
        "The session auto-saves after each exercise. "
        "Let me also add a quick-entry shorthand: `5x80` means 5 reps at 80kg.",
        OPUS, make_usage(1200, 840, cr=7400),
        tools=[tool_use_block("Edit", tid2, {"file_path": "workout/log.py",
            "old_string": "# parse reps/weight",
            "new_string": "m = re.match(r'(\\d+)x(\\d+\\.?\\d*)', entry)"})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid2, "Edit applied."))

    t += timedelta(seconds=5)
    entries.append(asst_entry(sid, t,
        "Done. The shorthand parser handles `5x80`, `3x12`, and `10x0` (bodyweight).",
        OPUS, make_usage(380, 130, cr=7400)))

    return entries


def session_workout_3(base: datetime) -> list[dict]:
    sid = SID_WORKOUT_3
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "Add personal record detection. After each set, check if it's a new PR "
        "for that exercise (heaviest weight, most reps at a given weight). "
        "Print a congratulations message if so."))

    t += timedelta(seconds=10)
    tid1 = "tool_j1"
    entries.append(asst_entry(sid, t,
        "I'll query the historical max for each exercise after inserting a new set. "
        "Two PR types: 1-rep-max equivalent using Epley formula, and reps-at-weight.",
        SONNET, make_usage(2600, 1120, cw=5800),
        tools=[tool_use_block("Edit", tid1, {"file_path": "workout/log.py",
            "old_string": "# check PR",
            "new_string": "pr = check_pr(conn, exercise_id, reps, weight)"})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "Edit applied."))

    t += timedelta(seconds=5)
    entries.append(asst_entry(sid, t,
        "New PRs print: `🏆 New PR! Heaviest squat: 120 kg (prev 117.5 kg)`. "
        "PRs are also logged to a `personal_records` table for history.",
        SONNET, make_usage(640, 220, cr=5800)))

    return entries


# ---------------------------------------------------------------------------
# macOS sessions
# ---------------------------------------------------------------------------

def session_photo_1(base: datetime) -> list[dict]:
    sid = SID_PHOTO_1
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "Write a Python script to batch rename RAW photo files (CR3, ARW, NEF) "
        "using their EXIF capture date. Target format: YYYYMMDD_HHMMSS_original-name.ext"))

    t += timedelta(seconds=9)
    tid1 = "tool_k1"
    entries.append(asst_entry(sid, t,
        "I'll use `exifread` for CR3/ARW/NEF — it handles all three without shelling out to exiftool.",
        SONNET, make_usage(1560, 880),
        tools=[tool_use_block("Write", tid1, {"file_path": "photo_tools/rename_by_date.py",
            "content": "import exifread\nfrom pathlib import Path\n..."})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "File written."))

    t += timedelta(seconds=4)
    entries.append(user_entry(sid, t,
        "Some files don't have EXIF data (screenshots, exports). Can it fall back to file mtime?"))

    t += timedelta(seconds=6)
    entries.append(asst_entry(sid, t,
        "Yes — I'll add a `--fallback-mtime` flag. Files without EXIF tags get renamed from mtime, "
        "prefixed with `MTIME_` so you can spot them.",
        SONNET, make_usage(2100, 480, cr=2800)))

    return entries


def session_photo_2(base: datetime) -> list[dict]:
    sid = SID_PHOTO_2
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "After renaming, sort the photos into a Year/Month folder hierarchy. "
        "Example: Photos/2025/11-November/filename.CR3"))

    t += timedelta(seconds=8)
    tid1 = "tool_l1"
    entries.append(asst_entry(sid, t,
        "I'll add a `sort_into_folders.py` script that reads the date prefix "
        "from the already-renamed files and moves them into the hierarchy.",
        SONNET, make_usage(1380, 740),
        tools=[tool_use_block("Write", tid1, {"file_path": "photo_tools/sort_into_folders.py",
            "content": "from pathlib import Path\nimport re\nimport shutil\n..."})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "File written."))

    t += timedelta(seconds=5)
    entries.append(asst_entry(sid, t,
        "Run with `--dry-run` first to preview moves without touching files. "
        "Pass `--copy` to copy instead of move if you want to keep originals.",
        SONNET, make_usage(520, 190, cr=2600)))

    return entries


def session_photo_3(base: datetime) -> list[dict]:
    sid = SID_PHOTO_3
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "Generate an HTML contact sheet from a directory of JPEGs — "
        "a grid of thumbnails with filename and date underneath, no dependencies."))

    t += timedelta(seconds=11)
    tid1 = "tool_m1"
    entries.append(asst_entry(sid, t,
        "I'll base64-encode small thumbnails into the HTML so it's fully self-contained. "
        "Uses Pillow to resize and PIL's built-in JPEG encoder.",
        OPUS, make_usage(2200, 1480, cw=7200),
        tools=[tool_use_block("Write", tid1, {"file_path": "photo_tools/contact_sheet.py",
            "content": "from PIL import Image\nimport base64\n..."})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "File written."))

    t += timedelta(seconds=5)
    entries.append(asst_entry(sid, t,
        "Run: `python contact_sheet.py ./Photos/2025/11-November/ --cols 5 --thumb 240`\n"
        "Outputs `contact_sheet.html` — open in any browser and print.",
        OPUS, make_usage(480, 200, cr=7200)))

    return entries


def session_photo_4(base: datetime) -> list[dict]:
    sid = SID_PHOTO_4
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "The renamer crashes on some Fujifilm RAF files with a KeyError on 'Image DateTime'. "
        "Here's the traceback: KeyError: 'Image DateTime' in rename_by_date.py line 42"))

    t += timedelta(seconds=7)
    tid1 = "tool_n1"
    entries.append(asst_entry(sid, t,
        "Fujifilm RAF stores the timestamp in `EXIF DateTimeOriginal` not `Image DateTime`. "
        "I'll update the tag lookup to try multiple tag names in priority order.",
        HAIKU, make_usage(980, 420),
        tools=[tool_use_block("Read", tid1, {"file_path": "photo_tools/rename_by_date.py"})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "# file content..."))

    t += timedelta(seconds=5)
    tid2 = "tool_n2"
    entries.append(asst_entry(sid, t,
        "Fixed. The lookup now tries: `EXIF DateTimeOriginal`, `Image DateTime`, "
        "`GPS GPSDate` in that order before falling back to mtime.",
        HAIKU, make_usage(1400, 360, cr=1800),
        tools=[tool_use_block("Edit", tid2, {"file_path": "photo_tools/rename_by_date.py",
            "old_string": "tags['Image DateTime']",
            "new_string": "next((tags[k] for k in DATE_TAGS if k in tags), None)"})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid2, "Edit applied."))

    t += timedelta(seconds=3)
    entries.append(asst_entry(sid, t,
        "RAF files should rename correctly now. Test with a small batch first.",
        HAIKU, make_usage(320, 90, cr=1800)))

    return entries


def session_rust_1(base: datetime) -> list[dict]:
    sid = SID_RUST_1
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "I'm a Python developer learning Rust. "
        "Explain ownership and borrowing in terms I'd already understand from Python — "
        "what's the mental model shift?"))

    t += timedelta(seconds=14)
    entries.append(asst_entry(sid, t,
        "Great starting point. In Python, every object is reference-counted and the GC handles cleanup. "
        "In Rust, the compiler tracks ownership statically at compile time — no runtime cost.\n\n"
        "The key mental shift: in Python you pass references freely and trust the GC. "
        "In Rust, every value has exactly one owner at a time. When the owner goes out of scope, "
        "the value is dropped — no GC needed.\n\n"
        "**Borrowing** is Rust's way of letting you temporarily use a value without taking ownership. "
        "Think of it like a Python context manager — you borrow it for a scope, then it goes back.",
        OPUS, make_usage(1800, 1640, cw=4200)))

    t += timedelta(seconds=8)
    entries.append(user_entry(sid, t,
        "What about mutable vs immutable borrows? "
        "When would I hit a borrow checker error?"))

    t += timedelta(seconds=12)
    entries.append(asst_entry(sid, t,
        "The rule: you can have **either** one mutable borrow **or** any number of immutable borrows "
        "at the same time — never both.\n\n"
        "In Python terms: imagine a list you're iterating over. If you mutate it mid-loop, "
        "bad things happen. Rust prevents that at compile time.\n\n"
        "Common borrow errors:\n"
        "1. Holding a `&mut` reference and then passing the value somewhere else\n"
        "2. Returning a reference to a local variable (dangling pointer — Rust rejects this)\n"
        "3. Trying to mutate through two paths simultaneously",
        OPUS, make_usage(2600, 980, cr=4200)))

    return entries


def session_rust_2(base: datetime) -> list[dict]:
    sid = SID_RUST_2
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "I'm writing a simple string parser that splits on a delimiter and returns slices. "
        "Getting lifetime errors I don't understand:\n\n"
        "```rust\nerror[E0106]: missing lifetime specifier\n"
        "fn split_first(s: &str, delim: char) -> &str\n```"))

    t += timedelta(seconds=10)
    entries.append(asst_entry(sid, t,
        "This is a classic lifetime annotation situation. The compiler needs to know: "
        "how long does the returned `&str` live relative to the input `s`?\n\n"
        "The fix is to explicitly link the lifetimes:\n\n"
        "```rust\nfn split_first<'a>(s: &'a str, delim: char) -> &'a str\n```\n\n"
        "This tells the compiler: 'the returned slice lives at least as long as `s`.' "
        "Which makes sense — a slice of `s` can't outlive `s` itself.",
        SONNET, make_usage(1640, 860, cw=3800)))

    t += timedelta(seconds=6)
    entries.append(user_entry(sid, t,
        "Makes sense! What if the function could return a slice of either `s` or a second string?"))

    t += timedelta(seconds=8)
    entries.append(asst_entry(sid, t,
        "Then you'd have two input lifetimes and need to constrain the output to the shorter one:\n\n"
        "```rust\nfn pick_first<'a, 'b>(s: &'a str, t: &'b str) -> &'a str\n```\n\n"
        "Or if the return could be from either, you'd need both to share a lifetime: `'a: 'b`.\n\n"
        "In practice, this kind of function is rare — most parsers return `String` (owned) "
        "or use `Cow<str>` to handle both cases without lifetime gymnastics.",
        SONNET, make_usage(2200, 620, cr=3800)))

    return entries


def session_rust_3(base: datetime) -> list[dict]:
    sid = SID_RUST_3
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "I have a Python script that parses a 2GB CSV of sensor readings and aggregates by hour. "
        "It takes 4 minutes. I want to rewrite it in Rust. Help me port it?"))

    t += timedelta(seconds=13)
    tid1 = "tool_o1"
    entries.append(asst_entry(sid, t,
        "For a streaming CSV parser in Rust, `csv` + `chrono` is the idiomatic choice. "
        "Here's the full port — should run in under 15 seconds.",
        OPUS, make_usage(3200, 2200, cw=8600),
        tools=[tool_use_block("Write", tid1, {"file_path": "sensor_agg/src/main.rs",
            "content": "use csv::Reader;\nuse chrono::prelude::*;\nuse std::collections::HashMap;\n..."})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid1, "File written."))

    t += timedelta(seconds=8)
    tid2 = "tool_o2"
    entries.append(asst_entry(sid, t,
        "Also adding a `Cargo.toml` with the needed dependencies.",
        OPUS, make_usage(1100, 380, cr=8600),
        tools=[tool_use_block("Write", tid2, {"file_path": "sensor_agg/Cargo.toml",
            "content": "[dependencies]\ncsv = '1.3'\nchrono = { version = '0.4', features = ['serde'] }"})]))

    t += timedelta(seconds=2)
    entries.append(tool_result_entry(sid, t, tid2, "File written."))

    t += timedelta(seconds=5)
    tid3 = "tool_o3"
    entries.append(asst_entry(sid, t,
        "Build and run with: `cargo run --release -- sensors.csv output.csv`\n"
        "The `--release` flag is critical for performance — debug builds are 10-100x slower.",
        OPUS, make_usage(560, 210, cr=8600),
        tools=[tool_use_block("Bash", tid3, {"command": "cd sensor_agg && cargo build --release 2>&1 | tail -5"})]))

    t += timedelta(seconds=4)
    entries.append(tool_result_entry(sid, t, tid3,
        "Compiling sensor_agg v0.1.0\nFinished release [optimized] target(s) in 3.42s"))

    t += timedelta(seconds=3)
    entries.append(asst_entry(sid, t,
        "Compiled successfully. The release binary is at `target/release/sensor_agg`.",
        OPUS, make_usage(340, 80, cr=8600)))

    return entries


def session_writing_1(base: datetime) -> list[dict]:
    sid = SID_WRITING_1
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "I want to write a sci-fi short story (5,000-8,000 words) set 200 years from now "
        "on a generation ship. The theme is memory and identity — what makes you 'you' "
        "when you're a copy of a copy. Help me develop the concept and outline."))

    t += timedelta(seconds=16)
    entries.append(asst_entry(sid, t,
        "This is a rich premise. Here are three structural approaches:\n\n"
        "**1. The Palimpsest** — Each generation is a 'copy' with memories of the previous generation "
        "edited in. Your protagonist discovers an unedited memory shard that doesn't belong to them.\n\n"
        "**2. The Ship's Log** — Told through logs written by 'the same person' across six generations. "
        "The reader slowly realises the handwriting and phrasing have subtly drifted.\n\n"
        "**3. The Vote** — The ship is about to arrive. The crew must decide whether to wake "
        "the original 200-year-old colonists (in cryo) or the people who've lived six generations "
        "of ship life. Who has a claim to the destination?\n\n"
        "I'd suggest option 3 — it has the most external conflict to carry the philosophical weight.",
        OPUS, make_usage(2200, 1820, cw=5400)))

    t += timedelta(seconds=10)
    entries.append(user_entry(sid, t, "I love option 3. Help me outline act structure and key scenes."))

    t += timedelta(seconds=14)
    entries.append(asst_entry(sid, t,
        "**Three-act outline:**\n\n"
        "**Act 1 (opening — inciting incident)**\n"
        "- Mira (ship-born, age 28) is head of navigation on final approach\n"
        "- Cryo bay shows anomalous activity — one of the original colonists is waking early\n"
        "- This triggers the constitutional 'Claim Clause': originals vs. ship-born\n\n"
        "**Act 2 (confrontation)**\n"
        "- The woken colonist (Dr Vasek) has memories of Earth that feel more 'real' than Mira's copies\n"
        "- The ship AI reveals it has been managing 'memory drift' for generations\n"
        "- Mira finds her grandmother's unedited journal — the drift is visible\n\n"
        "**Act 3 (resolution)**\n"
        "- The vote happens; Mira argues that home isn't origin, it's continuity\n"
        "- Ambiguous ending: the planet is reached, both groups step out together",
        OPUS, make_usage(3400, 1640, cr=5400)))

    return entries


def session_writing_2(base: datetime) -> list[dict]:
    sid = SID_WRITING_2
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "Here's my opening paragraph — please review and suggest improvements:\n\n"
        "'The ship had been moving for so long that no one alive remembered Earth. "
        "Mira pressed her palm against the viewport glass and looked at the star ahead, "
        "which was still just a point of light, but bigger now. It would be her home, "
        "if the council decided she was allowed to call it that.'"))

    t += timedelta(seconds=12)
    entries.append(asst_entry(sid, t,
        "Strong bones — the stakes are clear immediately. A few suggestions:\n\n"
        "**The main issue** is that 'no one alive remembered Earth' is doing important work "
        "but gets buried in a passive construction. Lead with the specificity instead:\n\n"
        "*'Mira had never seen a sunrise. Neither had her mother, or her mother's mother, "
        "or the four generations before that. She pressed her palm to the viewport glass "
        "and watched the star ahead — still a point, but larger than yesterday.'*\n\n"
        "This version:\n"
        "- Opens with character embodiment, not exposition\n"
        "- The generational depth lands harder through counting\n"
        "- 'Larger than yesterday' does the 'we're arriving' work without stating it\n\n"
        "The last sentence about the council is good — keep it, but trim 'if the council decided "
        "she was allowed to.' → 'if the council let her.'",
        OPUS, make_usage(2600, 1260, cw=6800)))

    t += timedelta(seconds=6)
    entries.append(user_entry(sid, t, "That's much better. Can you try a version that's more tense/ominous?"))

    t += timedelta(seconds=10)
    entries.append(asst_entry(sid, t,
        "*'The cryo alarms had not sounded in sixty years. When they did, Mira was "
        "at the viewport, watching the destination grow. She'd spent her whole life "
        "watching it grow. Now it seemed to be watching back.'*\n\n"
        "This pulls the inciting incident (cryo alarm) into the opening, "
        "and the final line adds unease without explaining it.",
        OPUS, make_usage(1800, 480, cr=6800)))

    return entries


def session_writing_3(base: datetime) -> list[dict]:
    sid = SID_WRITING_3
    t = base
    entries = [perm_entry(sid, t)]

    t += timedelta(seconds=2)
    entries.append(user_entry(sid, t,
        "I need to worldbuild the generation ship's memory-editing technology. "
        "What would be realistic constraints on it 200 years from now, "
        "given current neuroscience? I want it grounded, not magic."))

    t += timedelta(seconds=15)
    entries.append(asst_entry(sid, t,
        "Good instinct to ground it. Here's a plausible framework based on extrapolating "
        "current neuroscience (optogenetics, engram research, connectomics):\n\n"
        "**What's plausible by 2225:**\n"
        "- Precise tagging and suppression of specific memory engrams (already partially demonstrated "
        "in mice by Tonegawa's lab)\n"
        "- Addition of 'synthetic episodic memories' — the brain can't reliably distinguish these from real ones "
        "if the emotional context matches\n"
        "- 'Semantic implants' (knowledge without experience) — more reliable than episodic\n\n"
        "**Realistic constraints for drama:**\n"
        "- Emotional tone is hard to fake — memories can be implanted but the body's somatic response "
        "sometimes doesn't match (nausea when 'remembering' zero-g you've never experienced)\n"
        "- Repeated editing accumulates noise — third-generation edited memories have artefacts "
        "(this gives Mira's grandmother's journal its tells)\n"
        "- You can't implant a memory of a specific person's face unless you have reference data — "
        "so 'Earth' memories are generic (oceans, wind) not personal\n\n"
        "This keeps the technology powerful but limited in exactly the ways that serve your plot.",
        OPUS, make_usage(3600, 2080, cw=9200)))

    return entries


# ---------------------------------------------------------------------------
# Bulk session generator
# ---------------------------------------------------------------------------

_BULK_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

_TOPICS: dict[str, list[str]] = {
    "recipe-app": [
        "Add pytest coverage for the ingredient parser",
        "Export recipes to Markdown",
        "Import a recipe from a URL",
        "Add nutritional totals per serving",
        "Build a weekly meal planner with shopping list export",
        "Fix: searching by tag returns duplicates",
    ],
    "budget-tracker": [
        "Add support for recurring transactions",
        "Build a savings goal tracker with progress bar",
        "Flag transactions above a configurable threshold",
        "Multi-currency support with live FX rate lookup",
        "Generate a monthly PDF summary report",
        "Category chart colours are hard to distinguish — fix accessibility",
    ],
    "workout-log": [
        "Add progress charts per exercise over time",
        "Recommend next session weight based on recent RPE",
        "Export the last 30 workouts to CSV",
        "Add a rest timer that pings after the configured interval",
        "Support bodyweight movements without a weight field",
        "Fix: duplicate entries logged on daylight saving changeover",
    ],
    "web-scraper": [
        "Scrape Hacker News top stories into SQLite",
        "Add pagination — follow next-page links automatically",
        "Handle rate limiting with exponential backoff",
        "Parse article dates from mixed formats",
        "Upsert semantics so re-runs don't duplicate rows",
        "Handle JS-rendered content with Playwright",
        "Add a --since flag to only fetch articles after a given date",
        "Rotate proxies to avoid IP blocks",
    ],
    "pygame-game": [
        "Pixel-perfect collision detection for the platformer",
        "Particle effect system — sparks when the player lands",
        "Tile map renderer loading Tiled .tmx files",
        "A* enemy pathfinding — enemies get stuck on corners",
        "High score screen with name entry",
        "Delta-time game loop to decouple speed from frame rate",
        "Simple physics: gravity, friction, variable jump height",
        "Sound effects without audio lag using pygame.mixer",
    ],
    "photo-organizer": [
        "Duplicate detection using perceptual hashing",
        "Extract GPS coordinates and plot on a map",
        "Batch convert HEIC files to JPEG",
        "Smart album grouping by location cluster",
        "Generate WebP thumbnails at three sizes",
        "Fix: EXIF rotation flag not applied to thumbnails",
    ],
    "learn-rust": [
        "Async HTTP client with Tokio and reqwest",
        "Custom error types with thiserror",
        "Trait objects vs generics — when to use each",
        "Deserialise nested JSON with serde",
        "CLI argument parsing with clap derive macros",
        "Write integration tests with a shared test fixture",
        "Cargo workspace for a multi-crate project",
        "Understand Pin, Unpin, and why async needs them",
    ],
    "notes-writing": [
        "Outline the second act — the pacing feels slow",
        "Rewrite this dialogue scene to feel less expository",
        "Develop the antagonist's backstory",
        "Check worldbuilding consistency across chapters 4–7",
        "Draft a query letter for literary agents",
        "Turn these bullet-point notes into a blog post",
    ],
    "mcp-server": [
        "Build an MCP server that exposes file search as a tool",
        "Add regex capability to the file search tool",
        "Fix schema validation error on MCP server startup",
        "Write integration tests for the MCP tool handlers",
        "Add rate limiting so the search tool doesn't hammer the FS",
        "Package the MCP server for npx distribution",
        "Build a tool that reads and summarises large log files",
        "Debug: Claude Code isn't discovering my MCP server config",
    ],
    "homelab": [
        "Docker Compose stack for Nextcloud with Postgres and Redis",
        "Nginx reverse proxy with SSL termination for multiple services",
        "Automate SSL renewal with certbot and a cron job",
        "Nightly backup script syncing volumes to S3",
        "Grafana and Prometheus stack for container monitoring",
        "WireGuard VPN for remote access to the homelab",
        "Pi-hole watchdog — restart container if DNS stops responding",
        "Fix Docker log rotation to stop filling the disk",
    ],
}

# (turns_lo, turns_hi, inp_lo, inp_hi, cw_lo, cw_hi, cr_lo, cr_hi, out_lo, out_hi)
_TIER_PARAMS = {
    "big":    (22, 45, 200_000, 500_000,  80_000, 200_000, 300_000, 1_500_000,  60_000, 200_000),
    "medium": ( 8, 20,  28_000,  85_000,   8_000,  32_000,  35_000,   230_000,   7_000,  30_000),
    "small":  ( 3,  8,   4_000,  22_000,       0,   6_000,   3_000,    52_000,   1_500,   9_500),
    "quick":  ( 2,  4,     600,   5_500,       0,   1_500,       0,     7_000,     300,   2_800),
}

_FOLLOWUPS = [
    "Can you also handle the case where the input is empty?",
    "That works. One more edge case — what if the file doesn't exist?",
    "I'm getting a TypeError on line 23. Here's the traceback:\n\nTypeError: expected str, got NoneType\n  File \"src/main.py\", line 23, in process\n    return item.strip()",
    "Can we refactor this to be more readable?",
    "What's the performance overhead of this approach?",
    "Can you add error handling for the network call?",
    "How would this scale to 10× the data?",
    "The tests pass but coverage says the else branch isn't hit.",
    "Can you add a short docstring explaining the parameters?",
    "Perfect. Can we also handle the `--dry-run` flag?",
    "What happens if two processes write to the file simultaneously?",
    "Can we add a progress indicator for the long-running loop?",
]

_PRELUDES = [
    "Let me read the current implementation first.",
    "I'll check the existing code.",
    "Let me look at how this is structured.",
    "I'll run the tests to see what's currently failing.",
    "Let me search for where that's defined.",
    "I'll take a look at the file.",
    "Let me check what files are in scope.",
]

_TOOL_INPUTS = {
    "Read":  ("Read",  {"file_path": "src/main.py"}),
    "Edit":  ("Edit",  {"file_path": "src/main.py", "old_string": "    pass  # TODO: implement", "new_string": "    return [x for x in items if x is not None]"}),
    "Write": ("Write", {"file_path": "src/utils.py", "content": "from pathlib import Path\nimport json\n\n\ndef load_json(path: str) -> dict:\n    with open(path, encoding='utf-8') as f:\n        return json.load(f)\n\n\ndef save_json(data: dict, path: str) -> None:\n    Path(path).parent.mkdir(parents=True, exist_ok=True)\n    with open(path, 'w', encoding='utf-8') as f:\n        json.dump(data, f, indent=2)\n\n\ndef ensure_dir(path: str) -> Path:\n    p = Path(path)\n    p.mkdir(parents=True, exist_ok=True)\n    return p\n"}),
    "Bash":  ("Bash",  {"command": "python -m pytest tests/ -q"}),
    "Glob":  ("Glob",  {"pattern": "src/**/*.py"}),
    "Grep":  ("Grep",  {"pattern": "def process", "type": "py"}),
}
_TOOL_KEYS = list(_TOOL_INPUTS.keys())

_TOOL_RESULTS = {
    "Read": [
        "from pathlib import Path\n\n\nclass DataLoader:\n    def __init__(self, path: str):\n        self.path = Path(path)\n\n    def load(self) -> list[dict]:\n        results = []\n        with open(self.path) as f:\n            for line in f:\n                line = line.strip()\n                if line:\n                    results.append({\"raw\": line})\n        return results\n\n    def validate(self, record: dict) -> bool:\n        return bool(record.get(\"raw\"))\n",
        "import sqlite3\nfrom contextlib import contextmanager\n\nDB_PATH = \"data.db\"\n\n\n@contextmanager\ndef get_conn():\n    conn = sqlite3.connect(DB_PATH)\n    conn.row_factory = sqlite3.Row\n    try:\n        yield conn\n        conn.commit()\n    except Exception:\n        conn.rollback()\n        raise\n    finally:\n        conn.close()\n\n\ndef fetch_all(query: str, params=()) -> list:\n    with get_conn() as conn:\n        return conn.execute(query, params).fetchall()\n",
        "use std::collections::HashMap;\nuse std::io::{self, BufRead};\n\npub fn parse_config(path: &str) -> HashMap<String, String> {\n    let file = std::fs::File::open(path).expect(\"config not found\");\n    let reader = io::BufReader::new(file);\n    let mut map = HashMap::new();\n    for line in reader.lines().flatten() {\n        if let Some((k, v)) = line.split_once('=') {\n            map.insert(k.trim().to_string(), v.trim().to_string());\n        }\n    }\n    map\n}\n",
        "import pygame\n\nTILE_SIZE = 32\n\n\nclass TileMap:\n    def __init__(self, width: int, height: int):\n        self.width = width\n        self.height = height\n        self.tiles: list[list[int]] = [[0] * width for _ in range(height)]\n\n    def get(self, x: int, y: int) -> int:\n        if 0 <= x < self.width and 0 <= y < self.height:\n            return self.tiles[y][x]\n        return -1\n\n    def set(self, x: int, y: int, tile_id: int) -> None:\n        if 0 <= x < self.width and 0 <= y < self.height:\n            self.tiles[y][x] = tile_id\n",
    ],
    "Edit":  ["OK"],
    "Write": ["OK"],
    "Bash": [
        ".....\n5 passed in 0.31s",
        "test_parse PASSED\ntest_validate PASSED\ntest_edge_empty PASSED\n\n3 passed in 0.12s",
        "FAILED tests/test_main.py::test_parse_empty - AssertionError: assert [] == None\n\n1 failed, 4 passed in 0.28s",
        "Running...\nCompiled 3 files\nWarning: unused variable `idx` at src/main.py:42\nBuild complete.",
        "Checking formatting...\nWould reformat src/main.py\nWould reformat src/utils.py\n2 files would be reformatted.",
    ],
    "Glob": [
        "src/main.py\nsrc/utils.py\nsrc/config.py\nsrc/__init__.py",
        "tests/test_main.py\ntests/test_utils.py\ntests/conftest.py",
        "src/main.py\nsrc/models/user.py\nsrc/models/item.py\nsrc/db/connection.py\nsrc/db/queries.py",
    ],
    "Grep": [
        "src/main.py:14:def process(items: list) -> list:\nsrc/utils.py:8:def process_batch(data):",
        "src/main.py:22:    def validate(self, record):\nsrc/main.py:31:    def validate_all(self, records):",
        "src/config.py:5:def load_config(path: str) -> dict:\nsrc/config.py:18:def save_config(cfg: dict, path: str) -> None:",
    ],
}

_ASST_TEXTS = [
    """Here's the updated implementation:

```python
def process(items: list) -> list:
    \"\"\"Filter and normalise items, skipping None and blank strings.\"\"\"
    if not items:
        return []
    return [str(item).strip() for item in items if item is not None]
```

The empty-input guard returns early, and `str().strip()` handles both `None`-adjacent values and whitespace. Let me know if you want stricter typing.""",

    """I've applied the fix. The root cause was an off-by-one in the slice — the last element was silently dropped:

```python
# before
results = data[0:len(data) - 1]

# after
results = data[:]
```

All five tests pass now. The missing branch in coverage was the single-element list case.""",

    """Here's a version that scales better — replacing the nested loop with a dict lookup brings this from O(n²) to O(n):

```python
def find_duplicates(items: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    dupes: list[str] = []
    for item in items:
        if item in seen:
            if seen[item] == 1:
                dupes.append(item)
            seen[item] += 1
        else:
            seen[item] = 1
    return dupes
```

At 10× data volume the original would take ~100× longer; this stays linear.""",

    """Added the `--dry-run` flag — it short-circuits before any writes and prints what would change:

```python
def run(args):
    changes = compute_changes(args.source, args.dest)
    if args.dry_run:
        for src, dst in changes:
            print(f"  would copy: {src} -> {dst}")
        return
    apply_changes(changes)
```

Run with `--dry-run` first to verify the diff, then without to apply. Both paths are covered by tests.""",

    """The refactored version uses a context manager — no scattered try/finally across callers:

```python
from contextlib import contextmanager

@contextmanager
def open_db(path: str):
    conn = sqlite3.connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

Every caller now gets automatic rollback on error with a single `with open_db(path) as conn:` line.""",

    """Done. The docstring follows Google style to match the rest of the module:

```python
def load_records(path: str, skip_header: bool = True) -> list[dict]:
    \"\"\"Load CSV records from *path* into a list of dicts.

    Args:
        path: Absolute or relative path to the CSV file.
        skip_header: If True, treat the first row as column names.
            Defaults to True.

    Returns:
        List of dicts, one per data row. Empty list if the file
        is missing or contains no data rows.

    Raises:
        ValueError: If the file exists but cannot be parsed as CSV.
    \"\"\"
```

Let me know if you prefer NumPy or reStructuredText style.""",

    """Here's the error handler with exponential backoff for transient failures:

```python
import time
from urllib.error import URLError, HTTPError

def fetch_with_retry(url: str, retries: int = 3, delay: float = 1.0) -> bytes:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.read()
        except HTTPError as e:
            if e.code in (400, 401, 403, 404):
                raise  # permanent — don't retry
            last_err = e
        except URLError as e:
            last_err = e
        if attempt < retries - 1:
            time.sleep(delay * (2 ** attempt))
    raise RuntimeError(f"failed after {retries} attempts: {last_err}") from last_err
```

Backoff sequence is 1 s, 2 s, 4 s. Permanent HTTP errors surface immediately.""",

    """The Rust version compiles and passes all tests:

```rust
pub fn find_duplicates(items: &[&str]) -> Vec<&str> {
    use std::collections::HashMap;
    let mut counts: HashMap<&str, usize> = HashMap::new();
    for &item in items {
        *counts.entry(item).or_insert(0) += 1;
    }
    let mut dupes: Vec<&str> = counts
        .into_iter()
        .filter(|(_, c)| *c > 1)
        .map(|(k, _)| k)
        .collect();
    dupes.sort_unstable();
    dupes
}
```

`sort_unstable` gives deterministic output without the allocation overhead of stable sort. Let me know if you need the owned-`String` version.""",

    """Here's the progress indicator using `tqdm` — drops in with one import:

```python
from tqdm import tqdm

def process_all(records: list[dict]) -> list[dict]:
    results = []
    for record in tqdm(records, desc="Processing", unit="rec"):
        results.append(transform(record))
    return results
```

If you'd rather avoid the dependency, the stdlib version is a bit more verbose but works the same way:

```python
total = len(records)
for i, record in enumerate(records, 1):
    print(f"\\r{i}/{total}", end="", flush=True)
    results.append(transform(record))
print()
```""",
]

_PROJ_FOLDERS: dict[str, tuple[str, str]] = {
    "recipe-app":      ("Windows", "C--Users-Alex-Projects-recipe-app"),
    "budget-tracker":  ("Windows", "C--Users-Alex-Projects-budget-tracker"),
    "workout-log":     ("Windows", "C--Users-Alex-Projects-workout-log"),
    "web-scraper":     ("Windows", "C--Users-Alex-Projects-web-scraper"),
    "pygame-game":     ("Windows", "C--Users-Alex-Projects-pygame-game"),
    "photo-organizer": ("macOS",   "Users-alex-dev-photo-organizer"),
    "learn-rust":      ("macOS",   "Users-alex-dev-learn-rust"),
    "notes-writing":   ("macOS",   "Users-alex-notes-writing"),
    "mcp-server":      ("macOS",   "Users-alex-dev-mcp-server"),
    "homelab":         ("macOS",   "Users-alex-dev-homelab"),
}


def bulk_session(sid: str, base_t: datetime, model: str, tier: str,
                 project_key: str, topic_idx: int) -> list[dict]:
    """Generate a realistic-looking session deterministically from its parameters."""
    rng   = random.Random(sid)
    tp    = _TIER_PARAMS[tier]
    turns = rng.randint(tp[0], tp[1])
    inp   = rng.randint(tp[2], tp[3])
    cw    = rng.randint(tp[4], tp[5])
    cr    = rng.randint(tp[6], tp[7])
    out   = rng.randint(tp[8], tp[9])

    topics    = _TOPICS.get(project_key, ["Help me with this"])
    first_msg = topics[topic_idx % len(topics)]
    n_tools   = {"big": turns // 3, "medium": max(1, turns // 4), "small": rng.randint(1, 3), "quick": 1}[tier]
    tool_set  = set(rng.sample(range(turns), min(n_tools, turns)))

    inp_pt = max(100, inp // turns)
    out_pt = max( 50, out // turns)
    cw_pt  = max(  0, cw  // max(1, turns // 3))
    cr_pt  = max(  0, cr  // max(1, turns - 2))

    t = base_t
    entries = [perm_entry(sid, t)]
    t += timedelta(seconds=rng.randint(2, 5))
    entries.append(user_entry(sid, t, first_msg))

    for i in range(turns):
        t += timedelta(seconds=rng.randint(4, 18))
        usage = make_usage(
            inp=max(100, inp_pt + rng.randint(-inp_pt // 3, inp_pt // 3)),
            out=max( 50, out_pt + rng.randint(-out_pt // 3, out_pt // 3)),
            cw=cw_pt if i < turns // 3 else 0,
            cr=cr_pt if i >= 2 else 0,
        )
        if i in tool_set:
            key  = rng.choice(_TOOL_KEYS)
            name, inp_data = _TOOL_INPUTS[key]
            tid  = f"t_{sid[:6]}_{i}"
            prelude = rng.choice(_PRELUDES)
            entries.append(asst_entry(sid, t, prelude, model, usage,
                                      tools=[tool_use_block(name, tid, inp_data)]))
            t += timedelta(seconds=rng.randint(1, 3))
            result = rng.choice(_TOOL_RESULTS.get(name, ["OK"]))
            entries.append(tool_result_entry(sid, t, tid, result))
        else:
            entries.append(asst_entry(sid, t, rng.choice(_ASST_TEXTS), model, usage))
        if i < turns - 1:
            t += timedelta(seconds=rng.randint(15, 180))
            entries.append(user_entry(sid, t, rng.choice(_FOLLOWUPS)))

    return entries


_W, _M = "Windows", "macOS"
_S, _O, _H = SONNET, OPUS, HAIKU
_b, _m, _s, _q = "big", "medium", "small", "quick"

# (days_from_2025-08-01, hour, platform, project_key, model, tier, topic_idx)
_BULK_SCHED = [
    # === Aug 2025 ===
    (  3, 21, _W, "web-scraper",    _S, _s, 0),
    (  6, 14, _M, "homelab",        _S, _m, 0),
    ( 10, 19, _W, "pygame-game",    _S, _s, 0),
    ( 13,  9, _M, "learn-rust",     _S, _m, 5),
    ( 18, 22, _W, "budget-tracker", _H, _q, 0),
    ( 22, 10, _M, "mcp-server",     _S, _m, 0),
    ( 25, 19, _W, "workout-log",    _H, _q, 0),
    ( 29, 15, _M, "homelab",        _S, _s, 1),
    # === Sep 2025 ===
    ( 33, 20, _W, "web-scraper",    _S, _m, 1),
    ( 35,  9, _M, "learn-rust",     _O, _b, 0),
    ( 37, 14, _W, "pygame-game",    _S, _m, 1),
    ( 40, 21, _M, "notes-writing",  _S, _m, 0),
    ( 43, 10, _W, "web-scraper",    _H, _q, 2),
    ( 45, 19, _M, "mcp-server",     _S, _m, 1),
    ( 48, 11, _W, "recipe-app",     _S, _s, 0),
    ( 51, 20, _M, "homelab",        _S, _m, 2),
    ( 54, 19, _W, "budget-tracker", _S, _m, 1),
    ( 58, 22, _M, "learn-rust",     _S, _s, 2),
    # === Oct 2025 ===
    ( 63, 14, _W, "web-scraper",    _S, _m, 3),
    ( 65, 20, _M, "mcp-server",     _S, _s, 2),
    ( 67, 10, _W, "pygame-game",    _O, _b, 2),
    ( 69, 21, _M, "homelab",        _S, _m, 3),
    ( 72, 19, _W, "web-scraper",    _H, _q, 4),
    ( 74, 14, _M, "notes-writing",  _S, _m, 1),
    ( 76, 20, _W, "recipe-app",     _S, _s, 1),
    ( 78, 10, _M, "learn-rust",     _S, _m, 3),
    ( 81, 21, _W, "workout-log",    _S, _m, 0),
    ( 84, 19, _M, "mcp-server",     _S, _m, 3),
    ( 87, 15, _W, "pygame-game",    _S, _s, 3),
    ( 89, 11, _M, "homelab",        _H, _q, 4),
    # === Nov 2025 (hand-crafted sessions also land here) ===
    ( 94, 20, _W, "web-scraper",    _S, _s, 5),
    ( 96, 14, _M, "mcp-server",     _O, _b, 4),
    ( 99, 10, _W, "budget-tracker", _S, _m, 2),
    (102, 21, _M, "homelab",        _S, _m, 5),
    (107, 19, _W, "pygame-game",    _H, _q, 4),
    (111, 14, _M, "learn-rust",     _O, _b, 4),
    (115, 20, _W, "recipe-app",     _H, _q, 2),
    (119, 15, _M, "notes-writing",  _S, _m, 2),
    # === Dec 2025 ===
    (124, 20, _W, "web-scraper",    _S, _m, 6),
    (126, 10, _M, "homelab",        _O, _b, 5),
    (128, 21, _W, "pygame-game",    _S, _m, 5),
    (130, 14, _M, "mcp-server",     _S, _m, 5),
    (133, 19, _W, "budget-tracker", _H, _q, 3),
    (136, 11, _M, "learn-rust",     _S, _m, 5),
    (139, 20, _W, "workout-log",    _S, _s, 1),
    (142, 14, _M, "notes-writing",  _S, _m, 3),
    (145, 21, _W, "web-scraper",    _S, _s, 7),
    (148, 10, _M, "homelab",        _S, _m, 7),
    (151, 19, _W, "recipe-app",     _S, _m, 3),
    (153, 15, _M, "mcp-server",     _H, _q, 6),
    # === Jan 2026 ===
    (155, 20, _W, "web-scraper",    _O, _b, 0),
    (157, 10, _M, "homelab",        _S, _m, 4),
    (159, 21, _W, "pygame-game",    _S, _m, 6),
    (161, 14, _M, "learn-rust",     _S, _m, 6),
    (163, 19, _W, "budget-tracker", _S, _s, 4),
    (165, 11, _M, "mcp-server",     _S, _m, 6),
    (167, 20, _W, "workout-log",    _H, _q, 2),
    (170, 14, _M, "notes-writing",  _S, _s, 4),
    (172, 21, _W, "recipe-app",     _H, _q, 5),
    (174, 10, _M, "homelab",        _S, _s, 7),
    (176, 20, _W, "pygame-game",    _S, _s, 7),
    (178, 14, _M, "mcp-server",     _O, _b, 7),
    (180, 19, _W, "web-scraper",    _H, _q, 3),
    (182, 11, _M, "learn-rust",     _S, _s, 7),
    (183, 20, _W, "workout-log",    _S, _s, 3),
    # === Feb 2026 ===
    (185, 20, _W, "workout-log",    _S, _m, 3),
    (187, 10, _M, "homelab",        _S, _m, 4),
    (189, 21, _W, "budget-tracker", _O, _b, 5),
    (191, 14, _M, "mcp-server",     _S, _s, 3),
    (193, 19, _W, "pygame-game",    _O, _b, 1),
    (196, 11, _M, "notes-writing",  _S, _m, 5),
    (198, 20, _W, "web-scraper",    _S, _m, 4),
    (200, 14, _M, "photo-organizer",_S, _m, 0),
    (202, 21, _W, "recipe-app",     _S, _s, 4),
    (205, 10, _M, "homelab",        _H, _q, 5),
    (207, 19, _W, "web-scraper",    _S, _s, 6),
    (210, 14, _M, "mcp-server",     _S, _m, 4),
    # === Mar 2026 ===
    (214, 20, _W, "pygame-game",    _S, _m, 4),
    (216, 10, _M, "learn-rust",     _O, _b, 7),
    (218, 21, _W, "budget-tracker", _S, _s, 5),
    (220, 14, _M, "homelab",        _S, _m, 6),
    (222, 19, _W, "workout-log",    _S, _m, 4),
    (224, 11, _M, "photo-organizer",_O, _b, 1),
    (226, 20, _W, "web-scraper",    _H, _q, 5),
    (228, 14, _M, "notes-writing",  _S, _s, 3),
    (230, 21, _W, "recipe-app",     _S, _m, 5),
    (232, 10, _M, "mcp-server",     _S, _s, 7),
    (234, 19, _W, "pygame-game",    _S, _s, 6),
    (236, 14, _M, "photo-organizer",_S, _m, 2),
    (238, 20, _W, "budget-tracker", _H, _q, 2),
    (240, 11, _M, "homelab",        _S, _m, 3),
    (242, 19, _W, "web-scraper",    _S, _m, 7),
    # === Apr 2026 ===
    (245, 20, _M, "mcp-server",     _O, _b, 6),
    (247, 10, _W, "workout-log",    _S, _s, 5),
    (249, 21, _M, "learn-rust",     _S, _m, 0),
    (251, 14, _W, "photo-organizer",_S, _m, 3),
    (253, 19, _M, "homelab",        _S, _s, 4),
    (255, 11, _W, "recipe-app",     _H, _q, 0),
    (257, 20, _M, "notes-writing",  _O, _b, 0),
    (259, 14, _W, "pygame-game",    _H, _q, 5),
]


# ---------------------------------------------------------------------------
# Session registry — maps (platform, project_folder) → list of session entry-lists
# ---------------------------------------------------------------------------

def build_sessions_registry() -> dict[str, dict[str, list]]:
    """Returns {platform: {project_folder: [session_entries, ...]}}"""
    global _entry_counter
    _entry_counter = {}  # reset so re-runs produce identical JSONL content

    base = datetime(2025, 11, 1, 9, 30, tzinfo=timezone.utc)
    d = timedelta

    reg: dict[str, dict[str, list]] = {
        "Windows": {
            "C--Users-Alex-Projects-recipe-app": [
                session_recipe_1(base + d(days=0,  hours=0)),
                session_recipe_2(base + d(days=3,  hours=2)),
                session_recipe_3(base + d(days=8,  hours=11)),
            ],
            "C--Users-Alex-Projects-budget-tracker": [
                session_budget_1(base + d(days=1,  hours=14)),
                session_budget_2(base + d(days=12, hours=10)),
                session_budget_3(base + d(days=19, hours=16)),
            ],
            "C--Users-Alex-Projects-workout-log": [
                session_workout_1(base + d(days=5,  hours=19)),
                session_workout_2(base + d(days=14, hours=20)),
                session_workout_3(base + d(days=28, hours=21)),
            ],
        },
        "macOS": {
            "Users-alex-dev-photo-organizer": [
                session_photo_1(base + d(days=2,  hours=15)),
                session_photo_2(base + d(days=9,  hours=13)),
                session_photo_3(base + d(days=21, hours=16)),
                session_photo_4(base + d(days=35, hours=10)),
            ],
            "Users-alex-dev-learn-rust": [
                session_rust_1(base + d(days=4,  hours=18)),
                session_rust_2(base + d(days=16, hours=14)),
                session_rust_3(base + d(days=32, hours=11)),
            ],
            "Users-alex-notes-writing": [
                session_writing_1(base + d(days=7,  hours=20)),
                session_writing_2(base + d(days=24, hours=21)),
                session_writing_3(base + d(days=40, hours=19)),
            ],
        },
    }

    # Add 100 bulk sessions spread across Aug 2025 → Apr 2026
    bulk_base = datetime(2025, 8, 1, 9, 0, tzinfo=timezone.utc)
    for i, (days, hour, plat, proj_key, model, tier, topic_idx) in enumerate(_BULK_SCHED):
        _, folder = _PROJ_FOLDERS[proj_key]
        sid = str(uuid.uuid5(_BULK_NS, f"bulk-{i:03d}"))
        t   = bulk_base + timedelta(days=days, hours=hour - 9)
        reg[plat].setdefault(folder, []).append(
            bulk_session(sid, t, model, tier, proj_key, topic_idx)
        )

    return reg


# ---------------------------------------------------------------------------
# Write JSONL files
# ---------------------------------------------------------------------------

def write_jsonl_files(registry: dict[str, dict[str, list]]) -> None:
    raw_root = DEMO / "RAWEVERYTHING"
    # Wipe existing demo data so re-runs don't accumulate duplicates
    if raw_root.exists():
        shutil.rmtree(raw_root)
    for platform, projects in registry.items():
        for proj_folder, sessions in projects.items():
            proj_dir = raw_root / platform / "projects" / proj_folder
            proj_dir.mkdir(parents=True, exist_ok=True)
            for i, entries in enumerate(sessions):
                session_id = entries[0].get("sessionId", f"demo-{i}")
                fname = proj_dir / f"{session_id}.jsonl"
                with open(fname, "w", encoding="utf-8") as f:
                    for entry in entries:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"  Wrote JSONL files to RAWEVERYTHING/")


# ---------------------------------------------------------------------------
# Run pipeline
# ---------------------------------------------------------------------------

def run_pipeline() -> None:
    python = sys.executable

    # Wipe old demo archives so re-runs are clean (never touches real Windows/macOS/)
    for platform in ("Windows", "macOS"):
        old = DEMO / platform
        if old.exists():
            shutil.rmtree(old)

    # Copy scripts into demo/ so build_session_archive.py finds RAWEVERYTHING
    # as a sibling (it always looks relative to __file__)
    for script in ("build_session_archive.py", "merge_archives.py", "jsonl_to_html.py"):
        shutil.copy2(ROOT / "scripts" / script, DEMO / script)

    for platform in ("Windows", "macOS"):
        out = DEMO / platform / "archive"
        print(f"\n  Building {platform} archive -> {out}")
        result = subprocess.run(
            [python, str(DEMO / "build_session_archive.py"), str(out)],
            cwd=str(DEMO),
            capture_output=True, text=True
        )
        print(result.stdout.strip())
        if result.returncode != 0:
            print("STDERR:", result.stderr.strip())
            sys.exit(f"build_session_archive.py failed for {platform}")

    print("\n  Merging archives...")
    result = subprocess.run(
        [python, str(DEMO / "merge_archives.py"), str(DEMO)],
        cwd=str(DEMO),
        capture_output=True, text=True
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print("STDERR:", result.stderr.strip())
        sys.exit("merge_archives.py failed")


# ---------------------------------------------------------------------------
# Patch index for dark mode + demo viewer placeholder
# ---------------------------------------------------------------------------

def patch_for_demo(src: Path) -> str:
    html = src.read_text(encoding="utf-8")

    # Default dark mode
    html = html.replace("let darkMode     = false;", "let darkMode     = true;")
    html = html.replace("<body>", '<body class="dark">')

    # Disable localStorage restore so dark mode persists in the demo
    html = html.replace(
        "try { const s = JSON.parse(localStorage.getItem('csv-state') || '{}');",
        "try { const s = {}; if (false) {"
    )

    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== Claude Code Session Viewer — Demo Generator ===\n")

    print("[1/4] Generating fictional session JSONL files...")
    registry = build_sessions_registry()
    write_jsonl_files(registry)

    print("\n[2/4] Running archive pipeline...")
    run_pipeline()

    merged = DEMO / "index.html"
    if not merged.exists():
        sys.exit("merge_archives.py did not produce demo/index.html")

    print("\n[3/4] Patching for dark mode...")
    patched = patch_for_demo(merged)

    out = DEMO / "example-index.html"
    out.write_text(patched, encoding="utf-8")
    print(f"  Written: {out}  ({out.stat().st_size // 1024} KB)")

    print("\n[4/4] Cleaning up demo script copies and intermediate index...")
    merged.unlink()
    for script in ("build_session_archive.py", "merge_archives.py", "jsonl_to_html.py"):
        (DEMO / script).unlink(missing_ok=True)
    shutil.rmtree(DEMO / "__pycache__", ignore_errors=True)

    print(f"\nDone! Open example-index.html to preview.")


if __name__ == "__main__":
    main()
