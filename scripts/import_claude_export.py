#!/usr/bin/env python3
"""
import_claude_export.py — Import Claude.ai conversation exports into the session archive.

Usage:
    python scripts/import_claude_export.py conversations.json
    python scripts/import_claude_export.py conversations.json projects.json
    python scripts/import_claude_export.py conversations.json projects.json --output /path/to/Claude.ai
    python scripts/import_claude_export.py conversations.json --output /path/to/Claude.ai

Output:
    Claude.ai/archive/index.html      — session index (merge_archives.py reads this)
    Claude.ai/archive/{uuid}.html     — one rendered page per conversation

After running, execute `python scripts/merge_archives.py` from the repo root to include
these conversations in the combined index alongside your Claude Code sessions.
"""

import json, sys, re, html as _html
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Token estimation from character counts
# Claude.ai exports have full content but no token counts. We estimate by
# splitting content into prose (natural language) and code/structured data,
# applying different chars-per-token ratios for each.
# ---------------------------------------------------------------------------

_PROSE_CPT = 4   # chars per token for natural language
_CODE_CPT  = 3   # chars per token for code, JSON, tool I/O, bash output


def estimate_tokens(messages: list) -> dict:
    """
    Walk every content block in the message list and estimate token counts.
    Returns {"input": N, "cache_write": 0, "cache_read": 0, "output": N}.

    Split:
      input tokens  — human text + tool results (fed back to model as context)
      output tokens — assistant text + tool_use calls + thinking blocks
    """
    prose_input = 0   # human text messages
    code_input  = 0   # tool results (JSON / bash output)
    prose_out   = 0   # assistant text responses
    code_out    = 0   # tool_use call bodies + thinking blocks

    for msg in messages:
        sender  = msg.get("sender", "")
        content = msg.get("content")

        if not content:
            # Fallback: top-level text field
            t = msg.get("text") or ""
            if sender == "human":
                prose_input += len(t)
            else:
                prose_out += len(t)
            continue

        if isinstance(content, str):
            if sender == "human":
                prose_input += len(content)
            else:
                prose_out += len(content)
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")

            if btype == "text":
                chars = len(block.get("text", ""))
                if sender == "human":
                    prose_input += chars
                else:
                    prose_out += chars

            elif btype == "thinking":
                # Extended thinking — output tokens, prose-ish
                chars = len(block.get("thinking", "") or block.get("text", ""))
                prose_out += chars

            elif btype == "tool_use":
                # Tool invocations in assistant turns — output tokens, code-like
                inp = block.get("input") or {}
                code_out += len(json.dumps(inp, ensure_ascii=False))

            elif btype == "tool_result":
                # Tool outputs fed back as context — input tokens, code-like
                rc = block.get("content") or []
                if isinstance(rc, list):
                    for item in rc:
                        if isinstance(item, dict) and item.get("type") == "text":
                            code_input += len(item.get("text", ""))
                elif isinstance(rc, str):
                    code_input += len(rc)

    input_tok  = prose_input // _PROSE_CPT + code_input  // _CODE_CPT
    output_tok = prose_out   // _PROSE_CPT + code_out    // _CODE_CPT

    return {
        "input":       max(1, input_tok),
        "cache_write": 0,
        "cache_read":  0,
        "output":      max(1, output_tok),
    }


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_OUT = Path(__file__).parent.parent / "Claude.ai"


# ---------------------------------------------------------------------------
# Text rendering helpers
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    return _html.escape(str(s), quote=True)


def text_to_html(text: str) -> str:
    """
    Convert Claude markdown to HTML.
    Handles: fenced code, inline code, headings, bold, italic,
    bullet/numbered lists, blockquotes, tables, horizontal rules, paragraphs.
    """
    if not text:
        return ""

    placeholders: list[str] = []

    def ph(html: str) -> str:
        idx = len(placeholders)
        placeholders.append(html)
        return f"\x00PH{idx}\x00"

    # 1. Fenced code blocks
    def replace_fence(m: re.Match) -> str:
        lang = (m.group(1) or "").strip()
        code = esc(m.group(2))
        lang_attr = f' class="language-{esc(lang)}"' if lang else ''
        return ph(
            f'<div class="code-block">'
            f'<button class="copy-btn" onclick="copyCode(this)">Copy</button>'
            f'<pre><code{lang_attr}>{code}</code></pre>'
            f'</div>'
        )
    text = re.sub(r"```([^\n]*)\n(.*?)```", replace_fence, text, flags=re.DOTALL)

    # Helper: render a collected block of pipe-table lines
    def render_table(tlines: list[str]) -> str:
        rows = []
        for tl in tlines:
            cells = [c.strip() for c in tl.strip().lstrip('|').rstrip('|').split('|')]
            rows.append(cells)
        if not rows:
            return ""
        # Detect separator row (e.g. |---|:---:|)
        def is_sep(row):
            return bool(row) and all(re.match(r'^[-: ]+$', c) for c in row if c.strip())
        has_header = len(rows) >= 2 and is_sep(rows[1])
        parts = ['<div class="md-table-wrap"><table class="md-table">']
        if has_header:
            parts.append('<thead><tr>')
            for cell in rows[0]:
                parts.append(f'<th>{inline_fmt(esc(cell))}</th>')
            parts.append('</tr></thead><tbody>')
            body_rows = rows[2:]
        else:
            parts.append('<tbody>')
            body_rows = rows
        for row in body_rows:
            if is_sep(row):
                continue  # skip any extra separator rows
            parts.append('<tr>')
            for cell in row:
                parts.append(f'<td>{inline_fmt(esc(cell))}</td>')
            parts.append('</tr>')
        parts.append('</tbody></table></div>')
        return ph('\n'.join(parts))

    # 2. Process line-by-line for block elements
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    in_ul = False
    in_ol = False
    in_bq = False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def close_bq():
        nonlocal in_bq
        if in_bq:
            out.append("</blockquote>")
            in_bq = False

    while i < len(lines):
        line = lines[i]

        # Placeholder lines — emit as-is
        if re.match(r"^\x00PH\d+\x00$", line.strip()):
            close_lists(); close_bq()
            out.append(line)
            i += 1
            continue

        # Horizontal rule (must check before unordered list to avoid --- ambiguity)
        if re.match(r"^[-*_]{3,}\s*$", line) and not re.match(r"^[-*+]\s", line):
            close_lists(); close_bq()
            out.append("<hr>")
            i += 1
            continue

        # Headings
        hm = re.match(r"^(#{1,6})\s+(.*)", line)
        if hm:
            close_lists(); close_bq()
            level = len(hm.group(1))
            content = inline_fmt(esc(hm.group(2)))
            out.append(f"<h{level}>{content}</h{level}>")
            i += 1
            continue

        # Markdown table — collect pipe rows, tolerating blank lines between them
        if re.match(r"^\s*\|", line):
            close_lists(); close_bq()
            tlines = []
            j = i
            while j < len(lines):
                if re.match(r"^\s*\|", lines[j]):
                    tlines.append(lines[j])
                    j += 1
                elif not lines[j].strip():
                    k = j + 1
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    if k < len(lines) and re.match(r"^\s*\|", lines[k]):
                        j = k
                    else:
                        break
                else:
                    break
            i = j
            out.append(render_table(tlines))
            continue

        # Blockquote — emit content raw so the paragraph grouping pass wraps it
        if line.startswith("> ") or line == ">":
            close_lists()
            if not in_bq:
                out.append("<blockquote>")
                in_bq = True
            content = inline_fmt(esc(line[2:] if line.startswith("> ") else ""))
            out.append(content)  # no <p> wrap here — final pass handles it
            i += 1
            continue
        elif in_bq:
            close_bq()

        # Unordered list
        ulm = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if ulm:
            close_bq()
            if not in_ul:
                close_lists()
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline_fmt(esc(ulm.group(2)))}</li>")
            i += 1
            continue

        # Ordered list
        olm = re.match(r"^(\s*)\d+[.)]\s+(.*)", line)
        if olm:
            close_bq()
            if not in_ol:
                close_lists()
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{inline_fmt(esc(olm.group(2)))}</li>")
            i += 1
            continue

        # Blank line — close lists/blockquotes, marks paragraph boundary
        if not line.strip():
            close_lists(); close_bq()
            out.append("")
            i += 1
            continue

        # Regular paragraph line
        close_lists(); close_bq()
        out.append(inline_fmt(esc(line)))
        i += 1

    close_lists(); close_bq()

    # 3. Group consecutive non-empty, non-block lines into <p> tags
    result: list[str] = []
    para_buf: list[str] = []
    BLOCK_TAGS = ("<h1", "<h2", "<h3", "<h4", "<h5", "<h6",
                  "<ul", "</ul", "<ol", "</ol", "<li",
                  "<blockquote", "</blockquote", "<hr", "<div",
                  "\x00PH")

    def flush_para():
        if para_buf:
            result.append("<p>" + "<br>".join(para_buf) + "</p>")
            para_buf.clear()

    for line in out:
        if not line:
            flush_para()
        elif any(line.lstrip().startswith(t) for t in BLOCK_TAGS):
            flush_para()
            result.append(line)
        else:
            para_buf.append(line)
    flush_para()

    # 4. Restore placeholders
    html = "\n".join(result)
    for idx, block in enumerate(placeholders):
        html = html.replace(f"\x00PH{idx}\x00", block)
        html = html.replace(esc(f"\x00PH{idx}\x00"), block)

    return html


def inline_fmt(text: str) -> str:
    """Apply inline markdown: bold, italic, inline code, links to already-escaped text."""
    ph_list: list[str] = []

    def iph(html: str) -> str:
        idx = len(ph_list)
        ph_list.append(html)
        return f"\x00I{idx}\x00"

    # Inline code (backticks) — protect first so bold/italic don't touch them
    text = re.sub(r"`([^`]+)`",
                  lambda m: iph(f'<code class="inline-code">{m.group(1)}</code>'),
                  text)

    # Bold+italic ***text*** or ___text___
    text = re.sub(r"\*{3}(.+?)\*{3}",
                  lambda m: iph(f"<strong><em>{m.group(1)}</em></strong>"), text)
    text = re.sub(r"_{3}(.+?)_{3}",
                  lambda m: iph(f"<strong><em>{m.group(1)}</em></strong>"), text)

    # Bold **text** or __text__
    text = re.sub(r"\*{2}(.+?)\*{2}",
                  lambda m: iph(f"<strong>{m.group(1)}</strong>"), text)
    text = re.sub(r"_{2}(.+?)_{2}",
                  lambda m: iph(f"<strong>{m.group(1)}</strong>"), text)

    # Italic *text* or _text_  (not touching word-internal underscores)
    text = re.sub(r"\*(.+?)\*",
                  lambda m: iph(f"<em>{m.group(1)}</em>"), text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)",
                  lambda m: iph(f"<em>{m.group(1)}</em>"), text)

    # Auto-links
    text = re.sub(r"(https?://[^\s<>\"']+)",
                  lambda m: iph(f'<a href="{m.group(1)}" target="_blank" rel="noopener">{m.group(1)}</a>'),
                  text)

    for idx, val in enumerate(ph_list):
        text = text.replace(f"\x00I{idx}\x00", val)

    return text


# ---------------------------------------------------------------------------
# Extract text from a message's content field
# ---------------------------------------------------------------------------

def extract_text(msg: dict) -> str:
    """
    Claude.ai messages have either a top-level `text` string
    or a `content` array of blocks like {"type":"text","text":"..."}.
    Return the concatenated plain text.
    """
    # Prefer content array (richer)
    content = msg.get("content")
    if content and isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    # Ignore tool results — not shown in web export
                    pass
        if parts:
            return "\n\n".join(p for p in parts if p)

    # Fallback to top-level text
    return msg.get("text") or ""


# ---------------------------------------------------------------------------
# Parse a single conversation
# ---------------------------------------------------------------------------

def parse_conversation(conv: dict, project: str, project_key: str) -> dict:
    """Return a metadata dict suitable for the SESSIONS JSON."""
    uuid      = conv.get("uuid", "")
    title     = conv.get("name", "").strip() or uuid[:16]
    created   = conv.get("created_at", "")
    updated   = conv.get("updated_at", "")
    messages  = conv.get("chat_messages", [])

    # Model — may or may not be present
    model_raw = conv.get("model", "") or ""
    models    = [model_raw] if model_raw else []

    # Dates
    def parse_dt(s: str):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    dt_start = parse_dt(created)
    dt_end   = parse_dt(updated)

    # Also look at first/last message timestamps
    if messages:
        dt_first = parse_dt(messages[0].get("created_at", ""))
        dt_last  = parse_dt(messages[-1].get("created_at", ""))
        if dt_first:
            dt_start = dt_first
        if dt_last and dt_last != dt_first:
            dt_end = dt_last

    # Turn count = human messages
    turns = sum(1 for m in messages if m.get("sender") == "human")

    # Token estimate — character-based, prose vs code rates
    tok = estimate_tokens(messages)
    total_tok = tok["input"] + tok["output"]
    model_key = models[0] if models else "claude-unknown"
    model_tokens = {model_key: tok} if total_tok > 0 else {}

    # Preview = first human message (truncated)
    preview = ""
    for m in messages:
        if m.get("sender") == "human":
            text = extract_text(m)
            if text:
                preview = text[:180].replace("\n", " ").strip()
                if len(text) > 180:
                    preview += "…"
            break

    # Search text = all message text concatenated (capped)
    search_parts: list[str] = []
    for m in messages:
        t = extract_text(m).strip()
        if t:
            search_parts.append(t)
    search_text = " ".join(search_parts)[:500]

    # Duration
    duration_min = None
    if dt_start and dt_end and dt_end > dt_start:
        duration_min = max(1, int((dt_end - dt_start).total_seconds() / 60))

    return {
        "session_id":      uuid,
        "title":           title,
        "project":         project,
        "project_key":     project_key,
        "html_file":       uuid + ".html",
        "start_ts":        dt_start.strftime("%Y-%m-%d %H:%M") if dt_start else "",
        "end_ts":          dt_end.strftime("%H:%M")            if dt_end   else "",
        "date_sort":       dt_start.isoformat()                if dt_start else "",
        "cost":            0.0,
        "turns":           turns,
        "total_tok":       total_tok,
        "models":          models,
        "duration_min":    duration_min,
        "tool_counts":     {},
        "top_tools":       "",
        "is_continuation": False,
        "search_text":     search_text,
        "preview":         preview,
        "model_costs":     {},
        "model_tokens":    model_tokens,
        # kept for HTML rendering, not in final index JSON
        "_messages":       messages,
    }


# ---------------------------------------------------------------------------
# Individual conversation HTML
# ---------------------------------------------------------------------------

CONV_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAFZElEQVR42r2XTW8bVRSGn3Pv2GO7SZ3ETZp+qKWIVigSXSB1wQ6BwhqxARagigViBb+AX8CSBQs2qBv+AR+iC5CoxAKBgiAVUltoqZw2H26TuI7tmXsPixmPx/Y4rQBha+TxfNz7nnPe855zhOKPASQ9F/79R9PDP+5B+Y82fOL1ZexcBZhfPrMiEct978LQlq1aK+D+0Y6+750x2tMSG617d9bze+UBGEDPnl053trd/Uy9roKYw/wphcYN7ha9gReRbyrl4PLW1u376Qt+BMDs3Kmv1cuqqk9jpaoFS2fwVUGSuyKC6jQA6VNijIi/2t7deCUPwAC+0Tj7bC+Kr6uqAwyCoDqyaTEnFcTg4i6qnqBUQ9UjIqAwWEEQVdQLYsNSaaXVun0dMBnbI/VnMu8KMm7IgMaJT0DxiV1iiaMOs3PPcGz5Ei4+QMRkjkgWA03oJQgaqzszsCYDYIRK5l3VFLmMsVQQY1ILA7zv432Equf8c+8wW38K76PEejT3TTdJ/ohRCfMABtG2I5TRSbqJCC7uEsddXnj5E85deJO43+bCxXe5df1zbvx2hXJ5DvVuNGCaY4YIaozNCw4Adgqp8yxwPqJ65AQrz3/A+s8fs797g9XXvuDR3h227/1AtbaEapyFSwZ+m5C0IcDgydRDEGPpHTzk9Mpl4qjDvTtXKYV1frr2Ifu7tyiH83gfZ1FMaKSjWaGTGTIBQDUl12ABBedjcDG2NMvvv3yKqlKuHgdgZ3MNa8N8cg713NpRlQOQ0bDmAFiUaJhZoqgqYgzHGkvYwIJKSrDEGgVEUlJmFif4nXM8eNAik5RhTIs94HDJIjJE51WphSHVao2dnU1Mhl5yUc65O33Ve2g0jhOW23Q6ncQT2atyeAgYSz4B4riHyAxnz79BGDZItCpdLFFZxAS0d2/S7bZ4sLNGFB0MGZDXUx3h4CQAyUmPIERxxNLiMuWax9kIqQFOx4q1YAyYvsX3HYvHl5mpxrRaLYzI6ObTOVCk3h5rDNaW2Oo2Ofn6aQ4ai6hzQy6kFppyie76Pu6+Y+vaDepSxxpDnDFQCwt9cFgL4b2nVpthb38fs7/D0z9+yUy9hssDSAXLWsP2xkPaex1utprsqaVam6HT2SIYFCwex4Gcu5JapMzNL7Bxr0mVNq/O/0Fj1iJiEWNGwNqSsLa3S7MXsUmb5kaTkydOsLO9lci318JKGYyJQLa5955KpcLRuQUetTtYO8NHXxkCCzs7G8RRP/OCqlIqlanPLxLHIb5yhHpZOFqfp1KtEkdRjrA8xgNprFQ9lcoRol6XY0uLSUgUrLUciQK2tzexqaQ776jXl5idaxBHEWKSzaJ+l0oYstvrEViLFpAgKOhcEpFRxRhD1O8RuzhLTkU5enSW+YUFUJ9qveBcTHv/Ya4xAWuDNOQ6tZcKJhVAc3CSZkPEZO4WoNc9QDkYSVcAY4LUkamKyrCo6hSuB0zr7SSRWWsHi5oUv4KVMa+ZMQt9kpo2SJoTKaoUYwAsFo/L9NyI5aDTptXaHFWynATnwU6EUpOLnc6jlCu5VLQFANTQww1BGiNEUUyz+ddEz1vUpE5rRwNbwhibK82ixph+HoBPGXOHyI3sY0xAaEtZHzjSzOv0yUMLVE2G3YComLuDemdSAOb9995aF/Q7EWvTax7UqXoH6kCdpr9JNUqvqc+OtErk7g2ewyVzgbUifL/64qVfB934yFywcPr8ybjdvaKqL3FYG85hbpjkiqYKICLfztTCt5vNm3fHB5ORFZeWzl2MvD9llDCO3eNnRUvx5GYhEKve0wsCaW5v/7k2Hs3/ezjlsOG0aDz/r8BMHc//Bg8rqxImKmAZAAAAAElFTkSuQmCC">
<style>
  :root {{
    --bg:        #0d1117;
    --surface:   #161b22;
    --surface-2: #1c2128;
    --border:    #30363d;
    --text:      #e6edf3;
    --text-2:    #8b949e;
    --text-3:    #484f58;
    --accent:    oklch(62% 0.22 243);
    --human-bg:  #1a2332;
    --human-border: #2d3f55;
    --asst-bg:   #161b22;
    --asst-border: #30363d;
    --code-bg:   #0d1117;
    --font:      -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    --font-mono: "Cascadia Code", "Fira Code", Consolas, Menlo, monospace;
    --radius:    8px;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    font-size: 14px;
    line-height: 1.6;
    min-height: 100vh;
  }}

  /* ── Header ── */
  .page-header {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    position: sticky;
    top: 0;
    z-index: 10;
  }}
  .back-link {{
    color: var(--text-2);
    text-decoration: none;
    font-size: 13px;
    font-family: var(--font-mono);
    padding: 4px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    flex-shrink: 0;
  }}
  .back-link:hover {{ color: var(--text); border-color: var(--accent); }}
  .header-meta {{
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }}
  .header-title {{
    font-size: 14px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .header-sub {{
    font-size: 11px;
    color: var(--text-2);
    font-family: var(--font-mono);
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }}
  .source-badge {{
    display: inline-block;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 6px;
    border-radius: 3px;
    background: oklch(62% 0.22 243 / 0.15);
    color: var(--accent);
    border: 1px solid oklch(62% 0.22 243 / 0.3);
    letter-spacing: 0.3px;
  }}

  /* ── Conversation ── */
  .conversation {{
    max-width: 860px;
    margin: 0 auto;
    padding: 24px 24px 80px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }}

  /* ── Message cards ── */
  .message {{
    border-radius: var(--radius);
    padding: 14px 18px;
    border: 1px solid var(--border);
    position: relative;
  }}
  .message.human {{
    background: var(--human-bg);
    border-color: var(--human-border);
    margin-left: 40px;
  }}
  .message.assistant {{
    background: var(--asst-bg);
    border-color: var(--asst-border);
    margin-right: 40px;
  }}
  .msg-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }}
  .msg-role {{
    font-size: 11px;
    font-weight: 700;
    font-family: var(--font-mono);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .message.human   .msg-role {{ color: var(--accent); }}
  .message.assistant .msg-role {{ color: oklch(62% 0.15 155); }}
  .msg-time {{
    font-size: 10px;
    color: var(--text-3);
    font-family: var(--font-mono);
    margin-left: auto;
  }}
  .copy-msg-btn {{
    font-size: 10px;
    color: var(--text-3);
    background: none;
    border: 1px solid transparent;
    border-radius: 4px;
    cursor: pointer;
    padding: 2px 6px;
    font-family: var(--font-mono);
  }}
  .copy-msg-btn:hover {{ color: var(--text-2); border-color: var(--border); }}

  /* ── Message body ── */
  .msg-body p {{ margin-bottom: 10px; }}
  .msg-body p:last-child {{ margin-bottom: 0; }}

  .msg-body h1, .msg-body h2, .msg-body h3,
  .msg-body h4, .msg-body h5, .msg-body h6 {{
    margin: 16px 0 6px;
    line-height: 1.3;
    font-weight: 600;
    color: var(--text);
  }}
  .msg-body h1 {{ font-size: 1.45em; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
  .msg-body h2 {{ font-size: 1.25em; border-bottom: 1px solid var(--border); padding-bottom: 4px; }}
  .msg-body h3 {{ font-size: 1.1em; }}
  .msg-body h4 {{ font-size: 1.0em; }}
  .msg-body h5 {{ font-size: 0.9em; color: var(--text-2); }}
  .msg-body h6 {{ font-size: 0.85em; color: var(--text-2); }}
  .msg-body h1:first-child, .msg-body h2:first-child,
  .msg-body h3:first-child {{ margin-top: 0; }}

  .msg-body ul, .msg-body ol {{
    padding-left: 1.5em;
    margin: 8px 0;
  }}
  .msg-body li {{ margin: 3px 0; }}
  .msg-body li > ul, .msg-body li > ol {{ margin: 2px 0; }}

  .msg-body blockquote {{
    border-left: 3px solid var(--accent);
    margin: 10px 0;
    padding: 6px 12px;
    background: oklch(20% 0.01 240 / 0.5);
    border-radius: 0 4px 4px 0;
    color: var(--text-2);
  }}
  .msg-body blockquote p {{ margin-bottom: 4px; }}
  .msg-body blockquote p:last-child {{ margin-bottom: 0; }}

  .msg-body hr {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 16px 0;
  }}

  .msg-body strong {{ font-weight: 600; color: var(--text); }}
  .msg-body em {{ font-style: italic; color: var(--text); }}

  /* ── Tables ── */
  .md-table-wrap {{
    overflow-x: auto;
    margin: 12px 0;
    border-radius: 6px;
    border: 1px solid var(--border);
  }}
  .md-table {{
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
  }}
  .md-table th {{
    background: var(--surface-2);
    color: var(--text);
    font-weight: 600;
    text-align: left;
    padding: 7px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  .md-table td {{
    padding: 6px 12px;
    border-bottom: 1px solid var(--border);
    color: var(--text-2);
    vertical-align: top;
  }}
  .md-table tr:last-child td {{ border-bottom: none; }}
  .md-table tr:nth-child(even) td {{ background: oklch(14% 0.01 240 / 0.4); }}

  /* ── Code blocks ── */
  .code-block {{
    position: relative;
    margin: 10px 0;
    border-radius: 6px;
    background: var(--code-bg);
    border: 1px solid var(--border);
    overflow: hidden;
  }}
  .code-block pre {{
    padding: 14px 16px;
    overflow-x: auto;
    font-family: var(--font-mono);
    font-size: 12.5px;
    line-height: 1.5;
    margin: 0;
  }}
  .copy-btn {{
    position: absolute;
    top: 6px;
    right: 8px;
    font-size: 10px;
    font-family: var(--font-mono);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-2);
    cursor: pointer;
    padding: 2px 8px;
    z-index: 1;
  }}
  .copy-btn:hover {{ color: var(--text); border-color: var(--accent); }}
  .copy-btn.copied {{ color: oklch(62% 0.15 155); border-color: oklch(62% 0.15 155); }}

  .inline-code {{
    font-family: var(--font-mono);
    font-size: 12.5px;
    background: oklch(20% 0.01 240);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 1px 5px;
  }}

  /* ── Attachments ── */
  .attachments {{
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }}
  .attachment-pill {{
    font-size: 11px;
    font-family: var(--font-mono);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 8px;
    color: var(--text-2);
  }}

  /* ── Scrollbar ── */
  ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
</style>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/vs2015.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script>
  document.addEventListener('DOMContentLoaded', function() {{
    document.querySelectorAll('pre code[class*="language-"]').forEach(function(el) {{
      hljs.highlightElement(el);
    }});
  }});
</script>
</head>
<body>

<div class="page-header">
  <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAD1ElEQVR42q2Wz24bVRTGf+feO+MxTeKkSZsGwgbMAgTdREJILCrYwIYXQAIWhX3Fe9BnQIgFLwEqSyQqgSpQkIIIaUnc1H+SOvGM7bn3sJjxn3ECAsGxbF+PR+fc833n++7ALASw/PewZa5p0krcunXL7e7u1lZXVw2sA51/lPXkpBa2t6PR/fv3xyzsWgCazebycTu9G4K+DSSKOCMQ9C8yCqCUH4KgHiUVK99Epv5pt7vXB3CAAfzjdnpX1dxW9SCgGghaNKhz+SbfGjwitvxdvAQBldvDfADwMWAN4Hd2dqLg9R0N3gM5qgqooqrM1oIqIqrqNa6taNmfSvlWNA8heFTf3dnZiQBvAPb3zxIRYgQLakEm0IkgAioiRoyNJD1vybWtN+T5F94TP05FxAio6HRI1CpE+/tnyQQiGo2xedxWi0oJQ9GuoogYRlmXF1/5kFqyTvfJD0TxMr/+/AUuuoKqr0BX8mMbjbHpdAr8q8RNMJ4kH/V56bVPSAfH/PbLV2zceJ2j379GxFb4qUSAXrl089cL6GdrVY91Ca2H98jSNsGP+On7z3DREmAJBT3l5qpl1iiKVAqgxX0hBJJ6neWVBvk4JfgeSSMBeaaATgOIQcTgXI3+06ekWYoRU6ZRer1LOhCRckSVpJYwyjJctM3S0iYachBBVRER8vycdNAm+D5xLWYwOAdn5oi4pEC1mcDG9S3c6ptcvXETnw+LDQBiIwanj+i2HlA3jzg+2i9a10l+rRboLfAcVKnFCXk+pv/yGdw8I8+yaQHjHKNWytmDFHcwJo4TNJwg1hZquNBBb5ZdS2m7OOZx6w/e733Lq0cPCEEQEVQhcsLDdp8f+12+O8q4snxtWnxxpqocIIQQiJOE5aUG6fk5uwdweNyl1+2U9IE1QlRf42RQI4oNyysrJJ06o/GoKKSLBdaA9mwC4ijCWsPWs9u0BsrhAHpdZTwujDKKIjY2NhBRrm8WWneRYzjMMNahixxU2S1EPxoNCcEjCE7guc2rczDAcJihKMNcMcbOEauXQDTlQKZQRVGNEPzUBHIfKmBaF5d2EjDGFE46CbNQYG0NnnRQVcUYQ5altI4O5gjTC0qddVv4aJZlZSeFaU+k7ACSJElVhyPAiwghqOl2O/MCr5iZXNAMOBshIqEQIvm6MVlv7hz2K43tzxXzkaqfqfoyAZZ+tfj/7LpB8V+enR5+AFhXeB8iq/YOJx5E3gKtB1Uzf4oVFnJxGCY3iBBUSQW9ZxruDqeFZi9ss9ls1oBapxPk3zxKrK8bBYZ7e3tD/uYY/98fW/4Ex+zZrTZ+m9IAAAAASUVORK5CYII=" width="22" height="22" alt="" style="border-radius:4px;flex-shrink:0">
  <a class="back-link" href="../index.html" onclick="if(window.history.length>1){{history.back();return false;}}">← Back</a>
  <div class="header-meta">
    <span class="header-title">{title}</span>
    <div class="header-sub">
      <span class="source-badge">Claude.ai</span>
      {date_str}
      {turns_str}
      {model_str}
      {project_str}
    </div>
  </div>
</div>

<div class="conversation">
{messages_html}
</div>

<script>
function copyCode(btn) {{
  const code = btn.nextElementSibling.querySelector('code');
  navigator.clipboard.writeText(code.innerText).then(() => {{
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = 'Copy'; btn.classList.remove('copied'); }}, 1500);
  }});
}}

function copyMsg(btn) {{
  const body = btn.closest('.message').querySelector('.msg-body');
  navigator.clipboard.writeText(body.innerText).then(() => {{
    btn.textContent = '✓';
    setTimeout(() => {{ btn.textContent = '⎘'; }}, 1500);
  }});
}}
</script>

</body>
</html>
"""


def render_conversation_html(meta: dict) -> str:
    messages = meta.get("_messages", [])

    msgs_html_parts: list[str] = []
    for msg in messages:
        sender = msg.get("sender", "").lower()
        if sender not in ("human", "assistant"):
            continue

        text    = extract_text(msg)
        body_html = text_to_html(text)
        if not body_html:
            continue

        role_label = "You" if sender == "human" else "Claude"
        css_class  = "human" if sender == "human" else "assistant"

        # Timestamp
        ts_str = ""
        ts_raw = msg.get("created_at", "")
        if ts_raw:
            try:
                dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                ts_str = dt.strftime("%H:%M")
            except Exception:
                pass

        # Attachments
        attach_html = ""
        attachments = msg.get("attachments", []) or []
        files       = msg.get("files", []) or []
        all_attach  = list(attachments) + list(files)
        if all_attach:
            pills = []
            for a in all_attach:
                name = ""
                if isinstance(a, dict):
                    name = a.get("file_name") or a.get("name") or a.get("filename") or ""
                if name:
                    pills.append(f'<span class="attachment-pill">📎 {esc(name)}</span>')
            if pills:
                attach_html = '<div class="attachments">' + "".join(pills) + "</div>"

        msgs_html_parts.append(f"""
<div class="message {css_class}">
  <div class="msg-header">
    <span class="msg-role">{esc(role_label)}</span>
    {f'<span class="msg-time">{esc(ts_str)}</span>' if ts_str else ''}
    <button class="copy-msg-btn" onclick="copyMsg(this)" title="Copy message">⎘</button>
  </div>
  <div class="msg-body">
    {body_html}
  </div>
  {attach_html}
</div>""")

    # Header fields
    date_str    = esc(meta["start_ts"])  if meta.get("start_ts")     else ""
    turns_str   = f'{meta["turns"]} turns'                           if meta.get("turns") else ""
    model_str   = esc(meta["models"][0]) if meta.get("models")       else ""
    project_str = esc(meta["project"])   if meta.get("project") not in ("", "Direct conversations") else ""

    return CONV_HTML.format(
        title         = esc(meta["title"]),
        date_str      = date_str,
        turns_str     = turns_str,
        model_str     = model_str,
        project_str   = project_str,
        messages_html = "\n".join(msgs_html_parts),
    )


# ---------------------------------------------------------------------------
# Archive index.html (just needs const SESSIONS = [...]; for merge_archives.py)
# ---------------------------------------------------------------------------

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Claude.ai — Conversation Archive</title>
</head>
<body>
<script>
const SESSIONS = {sessions_json};
</script>
<p style="font-family:monospace;color:#888;padding:20px">
  {count} conversations imported from Claude.ai.<br>
  Run <code>python scripts/merge_archives.py</code> from the repo root to include these
  in the combined session index.
</p>
</body>
</html>
"""


def write_index(sessions_data: list[dict], archive_dir: Path) -> None:
    # Strip internal keys before writing to JSON
    clean = [
        {k: v for k, v in s.items() if not k.startswith("_")}
        for s in sessions_data
    ]
    html = INDEX_HTML.format(
        sessions_json = json.dumps(clean, ensure_ascii=False),
        count         = len(clean),
    )
    (archive_dir / "index.html").write_text(html, encoding="utf-8")
    print(f"  Wrote index: {archive_dir / 'index.html'}  ({len(clean)} sessions)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    # --output DIR
    output_dir = DEFAULT_OUT
    for f in flags:
        if f.startswith("--output="):
            output_dir = Path(f.split("=", 1)[1])
        elif f == "--output" and flags.index(f) + 1 < len(flags):
            output_dir = Path(flags[flags.index(f) + 1])

    # Also handle: --output path as positional-like arg
    raw_args = sys.argv[1:]
    for i, a in enumerate(raw_args):
        if a == "--output" and i + 1 < len(raw_args):
            output_dir = Path(raw_args[i + 1])

    if not args:
        print(__doc__)
        sys.exit(1)

    conv_path = Path(args[0])
    proj_path = Path(args[1]) if len(args) >= 2 and Path(args[1]).suffix == ".json" else None

    if not conv_path.exists():
        sys.exit(f"ERROR: File not found: {conv_path}")

    # ── Load conversations ──────────────────────────────────────────────────
    print(f"Loading conversations: {conv_path}")
    conversations: list[dict] = json.loads(conv_path.read_text(encoding="utf-8"))
    if isinstance(conversations, dict):
        # Sometimes wrapped: {"conversations": [...]}
        conversations = conversations.get("conversations", [conversations])
    print(f"  Found {len(conversations)} conversations")

    # ── Load projects (optional) ────────────────────────────────────────────
    conv_to_project: dict[str, tuple[str, str]] = {}  # uuid → (name, key)
    if proj_path and proj_path.exists():
        print(f"Loading projects: {proj_path}")
        projects: list[dict] = json.loads(proj_path.read_text(encoding="utf-8"))
        if isinstance(projects, dict):
            projects = projects.get("projects", [projects])
        for p in projects:
            proj_name = p.get("name", "Unnamed project").strip()
            proj_uuid = p.get("uuid", proj_name)
            proj_key  = re.sub(r"[^a-z0-9_]", "-", proj_name.lower())[:40]
            # conversations field may be list of UUIDs or list of objects
            conv_refs = p.get("conversations", []) or []
            for ref in conv_refs:
                if isinstance(ref, str):
                    conv_to_project[ref] = (proj_name, proj_key)
                elif isinstance(ref, dict):
                    ref_uuid = ref.get("uuid", ref.get("id", ""))
                    if ref_uuid:
                        conv_to_project[ref_uuid] = (proj_name, proj_key)
        print(f"  Mapped {len(conv_to_project)} conversations to projects")

    # ── Set up output directories ───────────────────────────────────────────
    archive_dir = output_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output: {output_dir}")

    # ── Process each conversation ───────────────────────────────────────────
    sessions_data: list[dict] = []
    skipped = 0

    for conv in conversations:
        uuid = conv.get("uuid", "")
        if not uuid:
            skipped += 1
            continue

        proj_name, proj_key = conv_to_project.get(uuid, ("Direct conversations", "direct"))

        meta = parse_conversation(conv, proj_name, proj_key)

        # Render and write HTML
        html_path = archive_dir / (uuid + ".html")
        try:
            conv_html = render_conversation_html(meta)
            html_path.write_text(conv_html, encoding="utf-8")
        except Exception as e:
            print(f"  WARN: Could not render {uuid}: {e}")
            skipped += 1
            continue

        sessions_data.append(meta)

    # Sort by date descending (newest first)
    sessions_data.sort(key=lambda s: s.get("date_sort", ""), reverse=True)

    print(f"\n  Rendered: {len(sessions_data)} conversations  ({skipped} skipped)")

    # ── Write index ─────────────────────────────────────────────────────────
    write_index(sessions_data, archive_dir)

    print(f"""
Done. Next steps:
  1. Move (or symlink) the Claude.ai/ folder next to your Windows/ and macOS/ folders
  2. Run: python scripts/merge_archives.py
  The Claude.ai conversations will appear as a new platform in the combined index.
""")


if __name__ == "__main__":
    main()
