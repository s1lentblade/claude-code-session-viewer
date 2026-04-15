#!/usr/bin/env python3
"""
build_session_archive.py — Build a browsable archive of all Claude Code sessions.

Usage:
    python scripts/build_session_archive.py [output_dir]

Default output: <repo_root>/<OS>/archive/

Prerequisites:
    - Python 3.8+
    - jsonl_to_html.py in the same directory as this script (scripts/)

What it does:
    1. Finds JSONL session files — from <platform_dir>/jsonl/ if it exists,
       otherwise falls back to ~/.claude/projects/ (live system)
    2. Converts each to a chat HTML (skips already-converted unless --force)
    3. Generates index.html — a browsable landing page grouped by project
       with search, sort, and cost totals.

Flags:
    --sync        Copy new/changed JSONL files from ~/.claude/projects/ into
                  RAWEVERYTHING/{OS}/projects/ before building. Use this when
                  running on the machine whose sessions you want to archive.
    --force       Re-convert all sessions even if HTML already exists
    --index-only  Only rebuild the index, skip (re)converting sessions

Portable workflow (scripts on a removable drive):
    1. On each machine: python scripts/build_session_archive.py --sync
       Auto-detects OS (Windows / macOS), copies raw JSONL into
       RAWEVERYTHING/{OS}/projects/ and builds the archive into {OS}/archive/.
    2. Anywhere: python scripts/merge_archives.py  →  regenerates unified index.html
    3. Open index.html

Directory layout (relative to repo root):
    RAWEVERYTHING/Windows/projects/   raw JSONL from Windows machine
    RAWEVERYTHING/macOS/projects/     raw JSONL from macOS machine
    PROCESSED/archive/                built HTML archive (default output)
    index.html                        unified viewer (from merge_archives.py)

macOS / Linux:
    Same command — the script auto-detects the Claude config directory via
    $CLAUDE_CONFIG_DIR or falls back to ~/.claude/
"""

import importlib.util
import json
import os
import platform
import shutil
import sys
import re
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Load jsonl_to_html from sibling file
# ---------------------------------------------------------------------------

def load_converter() -> object:
    sibling = Path(__file__).parent / "jsonl_to_html.py"
    if not sibling.exists():
        sys.exit(f"ERROR: jsonl_to_html.py not found at {sibling}")
    spec = importlib.util.spec_from_file_location("jsonl_to_html", sibling)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def claude_dir() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if env:
        return Path(env)
    return Path.home() / ".claude"


def sync_jsonl(dest: Path) -> None:
    """
    Copy new/changed JSONL files from ~/.claude/projects/ into dest/.
    Preserves the {project-folder}/{session}.jsonl structure.
    Skips files that already exist with the same or newer mtime.
    """
    source = claude_dir() / "projects"
    if not source.exists():
        sys.exit(f"ERROR: Claude projects directory not found at {source}")

    dest.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0

    for jsonl in sorted(source.glob("*/*.jsonl")):
        project_folder = jsonl.parent.name
        out_dir  = dest / project_folder
        out_dir.mkdir(exist_ok=True)
        out_file = out_dir / jsonl.name

        if not out_file.exists() or jsonl.stat().st_mtime > out_file.stat().st_mtime:
            shutil.copy2(jsonl, out_file)
            copied += 1
        else:
            skipped += 1

    print(f"Sync: {copied} copied, {skipped} already up-to-date  ->  {dest}")


def decode_project_folder(name: str) -> str:
    """
    Convert encoded folder name back to a human-readable path.
    e.g. C--Users-Alex-my-project -> C:/Users/Alex/my-project
         Users--alex-projects    -> /Users/alex/projects  (macOS)
    """
    # Claude Code encodes path separators as '--' and omits ':' from drive letters
    parts = name.split("--")
    if not parts:
        return name

    # Windows: first part is single letter (drive)
    if len(parts[0]) == 1 and parts[0].isalpha():
        drive = parts[0].upper() + ":"
        rest  = "/".join(parts[1:])
        # Within each '--' segment, '-' was used for path separator on Windows
        return drive + "/" + rest

    # macOS/Linux: no drive letter — rejoin with /
    return "/" + "/".join(parts)


def project_display_name(folder_name: str) -> str:
    """Return the last 2-3 meaningful path components for display."""
    full = decode_project_folder(folder_name)
    # Split on / or \
    parts = [p for p in re.split(r'[/\\]', full) if p and p not in ('', ':')]
    # Drop drive letter only segment
    if parts and len(parts[0]) <= 3 and ':' in parts[0]:
        parts = parts[1:]
    # Return last 2 parts joined with /
    return " / ".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else folder_name)


# ---------------------------------------------------------------------------
# Title & metadata extraction (fast scan — no full parse)
# ---------------------------------------------------------------------------

_SKIP_PATTERNS = re.compile(
    r'^(<|Unknown skill|'
    r'\[Request interrupted|'
    r'compact|compacted|'
    r'\[local-command)',
    re.IGNORECASE,
)

_CONTINUATION_MARKERS = [
    "this session is being continued",
    "ran out of context",
    "previous conversation that ran out",
    "summary below covers the earlier",
]

_MAX_SEARCH = 500


def _is_good_title(text: str) -> bool:
    """Return True if text is a decent session title candidate."""
    t = text.strip()
    if len(t) < 8:
        return False
    if _SKIP_PATTERNS.match(t):
        return False
    return True


def quick_scan(jsonl_path: Path, mod) -> dict:
    """
    Fast pass through a JSONL file to extract metadata without full render.
    Returns dict with: title, project, start_ts, end_ts, cost, turns, models, session_id
    """
    title        = ""
    session_id   = ""
    custom_title = ""
    start_ts     = ""
    end_ts       = ""
    models: set[str] = set()

    # Cost accumulation
    agg = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0, "turns": 0}
    total_cost = 0.0
    model_costs: dict[str, float] = {}
    model_tokens: dict[str, dict] = {}

    user_candidates: list[str] = []

    # New fields
    tool_counts: dict[str, int] = {}
    is_continuation    = False
    continuation_checked = False
    search_parts: list[str] = []
    search_chars       = 0
    preview            = ""   # set from first real user message
    msg_hour_counts = [0] * 24   # user messages by hour (local time from timestamp)
    tok_hour_counts = [0] * 24   # assistant output tokens by hour

    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue

                t = obj.get("type", "")

                # Timestamps
                ts = obj.get("timestamp", "")
                if ts:
                    if not start_ts:
                        start_ts = ts
                    end_ts = ts

                if t == "permission-mode" and not session_id:
                    session_id = obj.get("sessionId", "")

                elif t == "custom-title":
                    custom_title = obj.get("title", "")

                elif t == "user" and not obj.get("isMeta"):
                    content = obj.get("message", {}).get("content", "")
                    candidate = ""
                    text_raw = ""
                    if isinstance(content, str):
                        text_raw = content.strip()
                        candidate = text_raw
                    elif isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "text":
                                text_raw = b.get("text", "").strip()
                                candidate = text_raw
                                break

                    # Continuation detection — check first real user message
                    is_this_continuation_msg = False
                    if not continuation_checked and text_raw:
                        tl = text_raw.lower()
                        if any(m in tl for m in _CONTINUATION_MARKERS):
                            is_continuation = True
                            is_this_continuation_msg = True
                        continuation_checked = True

                    # Skip the injected continuation summary as a title or search candidate
                    if candidate and _is_good_title(candidate) and not is_this_continuation_msg and len(user_candidates) < 10:
                        user_candidates.append(candidate[:120])

                    # Use first meaningful user message as hover preview
                    if not preview and text_raw and _is_good_title(text_raw) and not is_this_continuation_msg:
                        preview = text_raw[:180].replace("\n", " ").strip()
                        if len(text_raw) > 180:
                            preview += "…"

                    # Accumulate search text from real user messages
                    if text_raw and _is_good_title(text_raw) and not is_this_continuation_msg and search_chars < _MAX_SEARCH:
                        chunk = text_raw[:_MAX_SEARCH - search_chars]
                        search_parts.append(chunk)
                        search_chars += len(chunk)

                    # Track user message hour
                    if ts and not is_this_continuation_msg:
                        try:
                            dt_msg = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            msg_hour_counts[dt_msg.hour] += 1
                        except Exception:
                            pass

                elif t == "assistant":
                    msg   = obj.get("message", {})
                    model = msg.get("model", "")

                    # Skip synthetic entries — injected by Claude Code, not real API calls
                    if model == "<synthetic>":
                        continue

                    if model:
                        models.add(model)

                    usage = msg.get("usage", {})
                    if usage:
                        agg["input"]       += usage.get("input_tokens", 0)
                        agg["cache_write"] += usage.get("cache_creation_input_tokens", 0)
                        agg["cache_read"]  += usage.get("cache_read_input_tokens", 0)
                        agg["output"]      += usage.get("output_tokens", 0)
                        agg["turns"]       += 1
                        try:
                            tc = mod.calc_cost(usage, model or next(iter(models), ""))
                            total_cost += tc
                            if model:
                                if model not in model_costs:
                                    model_costs[model] = 0.0
                                    model_tokens[model] = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
                                model_costs[model] += tc
                                model_tokens[model]["input"]       += usage.get("input_tokens", 0)
                                model_tokens[model]["cache_write"] += usage.get("cache_creation_input_tokens", 0)
                                model_tokens[model]["cache_read"]  += usage.get("cache_read_input_tokens", 0)
                                model_tokens[model]["output"]      += usage.get("output_tokens", 0)
                        except Exception:
                            pass

                    # Track assistant output tokens by hour
                    if ts and usage:
                        try:
                            dt_msg = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            tok_hour_counts[dt_msg.hour] += usage.get("output_tokens", 0)
                        except Exception:
                            pass

                    # Tool counts
                    blocks = msg.get("content", [])
                    if isinstance(blocks, list):
                        for block in blocks:
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type", "")
                            if btype == "tool_use":
                                name = block.get("name", "unknown")
                                tool_counts[name] = tool_counts.get(name, 0) + 1

    except Exception:
        pass

    # Pick best title
    if custom_title:
        title = custom_title
    elif user_candidates:
        # Prefer first candidate that's not too long, looks like a question or statement
        for c in user_candidates:
            if len(c) >= 15:
                title = c[:80]
                break
        if not title:
            title = user_candidates[0][:80]
    else:
        title = session_id[:16] + "..." if session_id else jsonl_path.stem[:40]

    # Format dates
    def parse_ts(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    dt_start = parse_ts(start_ts)
    dt_end   = parse_ts(end_ts)

    # Top tools string (top 5 by count)
    sorted_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)
    top_tools = "  ".join(f"{n}×{c}" for n, c in sorted_tools[:5])

    # Duration in minutes
    duration_min = None
    try:
        if dt_start and dt_end:
            duration_min = max(1, int((dt_end - dt_start).total_seconds() / 60))
    except Exception:
        pass

    return {
        "session_id":      session_id or jsonl_path.stem,
        "title":           title,
        "start_ts":        dt_start.strftime("%Y-%m-%d %H:%M") if dt_start else "",
        "end_ts":          dt_end.strftime("%H:%M") if dt_end else "",
        "date_sort":       dt_start.isoformat() if dt_start else "",
        "cost":            total_cost,
        "turns":           agg["turns"],
        "total_tok":       agg["input"] + agg["cache_write"] + agg["cache_read"] + agg["output"],
        "models":          sorted(models),
        "jsonl_path":      jsonl_path,
        # enriched fields
        "duration_min":    duration_min,
        "tool_counts":     tool_counts,
        "top_tools":       top_tools,
        "is_continuation": is_continuation,
        "search_text":     " ".join(search_parts)[:500],
        "preview":         preview,
        "model_costs":     {k: round(v, 6) for k, v in model_costs.items()},
        "model_tokens":    model_tokens,
        "msg_hours":       msg_hour_counts,   # 24-element list: user msgs per hour
        "tok_hours":       tok_hour_counts,   # 24-element list: output tokens per hour
    }


# ---------------------------------------------------------------------------
# Index HTML
# ---------------------------------------------------------------------------

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Code — Session Archive</title>
<style>
  :root {{
    --bg:          #0d1117;
    --bg-card:     #161b22;
    --bg-hover:    #1c2128;
    --bg-selected: #1f2937;
    --border:      #30363d;
    --text:        #e6edf3;
    --text-dim:    #8b949e;
    --text-dimmer: #484f58;
    --accent:      #58a6ff;
    --accent2:     #f0883e;
    --green:       #3fb950;
    --yellow:      #d29922;
    --orange:      #f0883e;
    --red:         #f85149;
    --font-mono:   "Cascadia Code", "Fira Code", "Consolas", "Menlo", monospace;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 13px;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}

  /* ── Top bar ── */
  .topbar {{
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
    padding: 12px 20px;
    display: flex;
    align-items: center;
    gap: 20px;
    flex-shrink: 0;
    z-index: 10;
  }}
  .topbar .logo {{ color: var(--accent); font-size: 16px; font-weight: 700; letter-spacing: -0.3px; white-space: nowrap; }}
  .topbar .subtitle {{ color: var(--text-dim); font-size: 11px; }}
  .search-box {{
    flex: 1;
    max-width: 400px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 12px;
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 12px;
    outline: none;
  }}
  .search-box:focus {{ border-color: var(--accent); }}
  .search-box::placeholder {{ color: var(--text-dimmer); }}
  .sort-btn {{
    background: none;
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-dim);
    font-family: var(--font-mono);
    font-size: 11px;
    padding: 4px 10px;
    cursor: pointer;
  }}
  .sort-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .sort-btn.active {{ border-color: var(--accent); color: var(--accent); background: rgba(88,166,255,0.1); }}
  .topbar-stats {{ font-size: 11px; color: var(--text-dimmer); white-space: nowrap; }}
  .topbar-stats span {{ color: var(--text-dim); }}

  /* ── Layout ── */
  .layout {{
    display: flex;
    flex: 1;
    overflow: hidden;
  }}

  /* ── Sidebar ── */
  .sidebar {{
    width: 220px;
    flex-shrink: 0;
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 12px 0;
    background: var(--bg-card);
  }}
  .sidebar-label {{
    font-size: 10px;
    color: var(--text-dimmer);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    padding: 6px 16px 4px;
  }}
  .project-item {{
    padding: 7px 16px;
    cursor: pointer;
    border-left: 2px solid transparent;
    transition: background 0.1s;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .project-item:hover {{ background: var(--bg-hover); }}
  .project-item.active {{
    border-left-color: var(--accent);
    background: var(--bg-selected);
    color: var(--accent);
  }}
  .project-name {{ font-size: 12px; word-break: break-all; }}
  .project-count {{
    font-size: 10px;
    color: var(--text-dimmer);
    background: rgba(255,255,255,0.06);
    border-radius: 8px;
    padding: 1px 6px;
    flex-shrink: 0;
  }}

  /* ── Session list ── */
  .sessions-pane {{
    flex: 1;
    overflow-y: auto;
    padding: 16px 20px;
  }}

  .section-header {{
    font-size: 11px;
    color: var(--text-dimmer);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    padding: 8px 0 10px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .section-header span {{ color: var(--text-dim); }}

  .session-card {{
    display: block;
    background: var(--bg-card);
    border: 1px solid #8b949e;
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 8px;
    text-decoration: none;
    color: var(--text);
    transition: border-color 0.15s, background 0.15s;
    cursor: pointer;
  }}
  .session-card:hover {{
    border-color: rgba(88,166,255,0.4);
    background: var(--bg-hover);
  }}
  .card-row {{ display: flex; align-items: baseline; gap: 10px; }}
  .card-title {{
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .card-cost {{
    font-size: 12px;
    font-weight: 700;
    white-space: nowrap;
    flex-shrink: 0;
  }}
  .card-meta {{
    display: flex;
    gap: 12px;
    margin-top: 5px;
    font-size: 11px;
    color: var(--text-dimmer);
  }}
  .card-project {{
    color: rgba(88,166,255,0.7);
    font-size: 10px;
    margin-top: 3px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .pill {{
    background: rgba(255,255,255,0.05);
    border-radius: 4px;
    padding: 1px 5px;
    white-space: nowrap;
  }}

  .no-results {{
    color: var(--text-dimmer);
    font-size: 12px;
    padding: 40px 0;
    text-align: center;
  }}

  ::-webkit-scrollbar {{ width: 5px; height: 5px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
</style>
</head>
<body>

<div class="topbar">
  <div>
    <div class="logo">Claude Code</div>
    <div class="subtitle">Session Archive</div>
  </div>
  <input class="search-box" type="text" placeholder="Search sessions..." id="search" oninput="filter()">
  <button class="sort-btn active" id="sort-date"  onclick="setSort('date')">Date</button>
  <button class="sort-btn"        id="sort-cost"  onclick="setSort('cost')">Cost</button>
  <button class="sort-btn"        id="sort-turns" onclick="setSort('turns')">Turns</button>
  <div class="topbar-stats">
    {total_sessions} sessions &nbsp;|&nbsp; <span>{total_cost_str}</span> total
  </div>
</div>

<div class="layout">
  <div class="sidebar">
    <div class="sidebar-label">Projects</div>
    <div class="project-item active" onclick="selectProject('__all__')" id="proj-__all__">
      <span class="project-name">All sessions</span>
      <span class="project-count">{total_sessions}</span>
    </div>
{project_sidebar_html}
  </div>

  <div class="sessions-pane" id="sessions-pane">
    <!-- populated by JS -->
  </div>
</div>

<script>
const SESSIONS = {sessions_json};

let currentProject = '__all__';
let currentSort = 'date';

function costColor(c) {{
  if (c < 0.01)  return 'var(--green)';
  if (c < 0.10)  return 'var(--yellow)';
  if (c < 0.50)  return 'var(--orange)';
  return 'var(--red)';
}}

function fmtCost(c) {{
  if (c >= 1)    return '$' + c.toFixed(3);
  if (c >= 0.001) return '$' + c.toFixed(4);
  return '$' + c.toFixed(5);
}}

function fmtTok(n) {{
  if (n >= 1e6) return (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(1) + 'k';
  return String(n);
}}

function selectProject(key) {{
  currentProject = key;
  document.querySelectorAll('.project-item').forEach(el => el.classList.remove('active'));
  const el = document.getElementById('proj-' + key);
  if (el) el.classList.add('active');
  render();
}}

function setSort(key) {{
  currentSort = key;
  document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('sort-' + key).classList.add('active');
  render();
}}

function filter() {{ render(); }}

function render() {{
  const query   = document.getElementById('search').value.toLowerCase();
  const pane    = document.getElementById('sessions-pane');

  let items = SESSIONS.filter(s => {{
    if (currentProject !== '__all__' && s.project_key !== currentProject) return false;
    if (query && !s.title.toLowerCase().includes(query) && !s.project.toLowerCase().includes(query)) return false;
    return true;
  }});

  // Sort
  if (currentSort === 'date')  items.sort((a,b) => (b.date_sort||'').localeCompare(a.date_sort||''));
  if (currentSort === 'cost')  items.sort((a,b) => b.cost - a.cost);
  if (currentSort === 'turns') items.sort((a,b) => b.turns - a.turns);

  if (items.length === 0) {{
    pane.innerHTML = '<div class="no-results">No sessions match.</div>';
    return;
  }}

  // Group by project when showing all
  let html = '';
  if (currentProject === '__all__') {{
    const groups = {{}};
    items.forEach(s => {{
      if (!groups[s.project_key]) groups[s.project_key] = {{ name: s.project, items: [] }};
      groups[s.project_key].items.push(s);
    }});
    for (const [key, grp] of Object.entries(groups)) {{
      const grpCost = grp.items.reduce((a,s) => a+s.cost, 0);
      html += `<div class="section-header">${{grp.name}} <span>${{grp.items.length}} sessions &nbsp;·&nbsp; ${{fmtCost(grpCost)}}</span></div>`;
      grp.items.forEach(s => {{ html += sessionCard(s, false); }});
    }}
  }} else {{
    const grpCost = items.reduce((a,s) => a+s.cost, 0);
    html += `<div class="section-header">${{items[0].project}} <span>${{items.length}} sessions &nbsp;·&nbsp; ${{fmtCost(grpCost)}}</span></div>`;
    items.forEach(s => {{ html += sessionCard(s, false); }});
  }}

  pane.innerHTML = html;
}}

function sessionCard(s, showProject) {{
  const color = costColor(s.cost);
  const projLine = `<div class="card-project">${{s.project}}</div>`;
  return `
  <a class="session-card" href="${{s.html_file}}" target="_blank">
    <div class="card-row">
      <span class="card-title">${{escHtml(s.title)}}</span>
      <span class="card-cost" style="color:${{color}}">${{fmtCost(s.cost)}}</span>
    </div>
    ${{projLine}}
    <div class="card-meta">
      <span class="pill">${{s.start_ts || 'unknown date'}}</span>
      <span class="pill">${{s.turns}} turns</span>
      <span class="pill">${{fmtTok(s.total_tok)}} tok</span>
      ${{s.models.length ? '<span class="pill">' + s.models.map(m=>m.replace('claude-','')).join(', ') + '</span>' : ''}}
    </div>
  </a>`;
}}

function escHtml(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

// Initial render
render();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Build everything
# ---------------------------------------------------------------------------

def detect_os_name() -> str:
    """Return 'macOS' on Darwin, 'Windows' on Windows, 'Linux' otherwise."""
    s = platform.system()
    if s == "Darwin":
        return "macOS"
    if s == "Windows":
        return "Windows"
    return "Linux"


def run(output_dir: Path, force: bool = False, index_only: bool = False, sync: bool = False) -> None:
    mod = load_converter()

    # When running from scripts/ use repo root; when copied into demo/ or run standalone use parent dir
    _script_parent = Path(__file__).resolve().parent
    base_dir = _script_parent.parent if _script_parent.name == "scripts" else _script_parent

    # Track renderer mtime so that updating jsonl_to_html.py triggers reconversion
    _converter_path = _script_parent / "jsonl_to_html.py"
    _renderer_mtime = _converter_path.stat().st_mtime if _converter_path.exists() else 0.0

    # --sync always mirrors the CURRENT machine's sessions into RAWEVERYTHING
    current_os = detect_os_name()
    if sync:
        sync_jsonl(base_dir / "RAWEVERYTHING" / current_os / "projects")

    # Source is derived from the output platform folder name (e.g. "Windows", "macOS")
    # so you can build either platform's archive from any machine.
    platform_folder = output_dir.parent.name          # e.g. "Windows" or "macOS"
    raw_dir = base_dir / "RAWEVERYTHING" / platform_folder / "projects"
    if not raw_dir.exists() or not any(raw_dir.glob("*/*.jsonl")):
        # Fallback: try current machine's raw dir
        raw_dir = base_dir / "RAWEVERYTHING" / current_os / "projects"

    # Prefer RAWEVERYTHING copy, fall back to live ~/.claude/projects/
    if raw_dir.exists() and any(raw_dir.glob("*/*.jsonl")):
        count = sum(1 for _ in raw_dir.glob("*/*.jsonl"))
        print(f"Source: RAWEVERYTHING/{raw_dir.parent.name}/projects/  ({count} sessions)")
        projects_root = raw_dir
    else:
        projects_root = claude_dir() / "projects"
        if not projects_root.exists():
            sys.exit(
                f"ERROR: No JSONL source found.\n"
                f"  Checked: {raw_dir}\n"
                f"  Checked: {projects_root}\n"
                f"  Run with --sync to copy sessions from this machine first."
            )
        print(f"Source: live ~/.claude/projects/ at {projects_root}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Discover all sessions
    all_jsonl: list[Path] = sorted(projects_root.glob("*/*.jsonl"))
    print(f"Found {len(all_jsonl)} JSONL session files across {len(set(p.parent for p in all_jsonl))} projects")

    sessions_meta: list[dict] = []

    for i, jsonl in enumerate(all_jsonl, 1):
        project_folder = jsonl.parent.name
        html_name      = jsonl.stem + ".html"
        html_out       = output_dir / html_name

        print(f"  [{i}/{len(all_jsonl)}] Scanning {project_folder[:40]}/{jsonl.name[:16]}...", end=" ", flush=True)

        # Quick metadata scan
        meta = quick_scan(jsonl, mod)
        meta["project_folder"] = project_folder
        meta["project"]        = project_display_name(project_folder)
        meta["project_key"]    = project_folder
        meta["html_file"]      = html_name

        sessions_meta.append(meta)

        # Convert to HTML
        if not index_only:
            html_mtime = html_out.stat().st_mtime if html_out.exists() else 0.0
            html_is_fresh = (
                html_out.exists() and
                html_mtime >= jsonl.stat().st_mtime and
                html_mtime >= _renderer_mtime   # reconvert if jsonl_to_html.py changed
            )
            if html_is_fresh and not force:
                print(f"skip (up-to-date)")
            else:
                print(f"converting...")
                try:
                    mod.convert(jsonl, html_out)
                except Exception as e:
                    print(f"  ERROR: {e}")
        else:
            print("index-only mode")

    # Build index
    print(f"\nBuilding index.html ...")
    _build_index(sessions_meta, output_dir)

    index_path = output_dir / "index.html"
    print(f"\nDone. Open: {index_path}")
    print(f"  {len(sessions_meta)} sessions  |  Total est. cost: {mod.fmt_cost(sum(s['cost'] for s in sessions_meta))}")


def _build_index(sessions: list[dict], output_dir: Path) -> None:
    # Project sidebar
    by_project: dict[str, list] = {}
    for s in sessions:
        by_project.setdefault(s["project_key"], []).append(s)

    sidebar_html = ""
    for key, sess in sorted(by_project.items(), key=lambda kv: kv[0]):
        name = sess[0]["project"]
        count = len(sess)
        safe_key = key.replace('"', '&quot;')
        sidebar_html += (
            f'    <div class="project-item" onclick="selectProject(\'{safe_key}\')" id="proj-{safe_key}">\n'
            f'      <span class="project-name">{name}</span>\n'
            f'      <span class="project-count">{count}</span>\n'
            f'    </div>\n'
        )

    # Sessions JSON for JS
    import json as _json
    sessions_data = [
        {
            "session_id":      s["session_id"],
            "title":           s["title"],
            "project":         s["project"],
            "project_key":     s["project_key"],
            "html_file":       s["html_file"],
            "start_ts":        s["start_ts"],
            "end_ts":          s["end_ts"],
            "date_sort":       s["date_sort"],
            "cost":            round(s["cost"], 6),
            "turns":           s["turns"],
            "total_tok":       s["total_tok"],
            "models":          s["models"],
            "duration_min":    s.get("duration_min"),
            "tool_counts":     s.get("tool_counts", {}),
            "top_tools":       s.get("top_tools", ""),
            "is_continuation": s.get("is_continuation", False),
            "search_text":     s.get("search_text", ""),
            "preview":         s.get("preview", ""),
            "model_costs":     s.get("model_costs", {}),
            "model_tokens":    s.get("model_tokens", {}),
            "msg_hours":       s.get("msg_hours", [0]*24),
            "tok_hours":       s.get("tok_hours", [0]*24),
        }
        for s in sessions
    ]

    total_cost = sum(s["cost"] for s in sessions)

    # Use fmt_cost from the converter module
    loader = importlib.util.spec_from_file_location("jsonl_to_html", Path(__file__).parent / "jsonl_to_html.py")
    _mod = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(_mod)

    html = INDEX_TEMPLATE.format(
        total_sessions=len(sessions),
        total_cost_str=_mod.fmt_cost(total_cost),
        project_sidebar_html=sidebar_html,
        sessions_json=json.dumps(sessions_data, ensure_ascii=False),
    )

    (output_dir / "index.html").write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    force      = "--force"      in args
    index_only = "--index-only" in args
    sync       = "--sync"       in args
    args = [a for a in args if not a.startswith("--")]

    _sp = Path(__file__).resolve().parent
    base_dir    = _sp.parent if _sp.name == "scripts" else _sp
    default_out = base_dir / "PROCESSED" / "archive"
    output_dir  = Path(args[0]) if args else default_out

    run(output_dir, force=force, index_only=index_only, sync=sync)


if __name__ == "__main__":
    main()
