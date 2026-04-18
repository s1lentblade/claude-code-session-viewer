#!/usr/bin/env python3
"""
jsonl_to_html.py — Convert a Claude Code session JSONL file to a readable HTML page.

Usage:
    python scripts/jsonl_to_html.py <session.jsonl> [output.html]

If output path is omitted, writes alongside the input file with .html extension.
"""

import json
import sys
import re
import difflib
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------------------------
# Pricing — $ per million tokens (API list prices, Apr 2026)
# More-specific prefixes must come before less-specific ones (first match wins).
# Cache write uses the 5-minute TTL rate.
# ---------------------------------------------------------------------------

PRICING: dict[str, dict[str, float]] = {
    # Model slug prefix → {input, cache_write, cache_read, output}
    # Opus 4.7 / 4.6 / 4.5 — more-specific prefixes must precede "claude-opus-4"
    "claude-opus-4-7":   {"input":  5.00, "cache_write":  6.25, "cache_read": 0.50,  "output": 25.00},
    "claude-opus-4-6":   {"input":  5.00, "cache_write":  6.25, "cache_read": 0.50,  "output": 25.00},
    "claude-opus-4-5":   {"input":  5.00, "cache_write":  6.25, "cache_read": 0.50,  "output": 25.00},
    # Opus 4.1 / 4 / 3
    "claude-opus-4":     {"input": 15.00, "cache_write": 18.75, "cache_read": 1.50,  "output": 75.00},
    "claude-opus-3":     {"input": 15.00, "cache_write": 18.75, "cache_read": 1.50,  "output": 75.00},
    # Sonnet (all 4.x variants same price)
    "claude-sonnet-4":   {"input":  3.00, "cache_write":  3.75, "cache_read": 0.30,  "output": 15.00},
    "claude-sonnet-3-7": {"input":  3.00, "cache_write":  3.75, "cache_read": 0.30,  "output": 15.00},
    # Haiku 4.5
    "claude-haiku-4-5":  {"input":  1.00, "cache_write":  1.25, "cache_read": 0.10,  "output":  5.00},
    # Haiku 3.5 / 4 (original)
    "claude-haiku-4":    {"input":  0.80, "cache_write":  1.00, "cache_read": 0.08,  "output":  4.00},
    "claude-haiku-3-5":  {"input":  0.80, "cache_write":  1.00, "cache_read": 0.08,  "output":  4.00},
    # Haiku 3
    "claude-haiku-3":    {"input":  0.25, "cache_write":  0.30, "cache_read": 0.03,  "output":  1.25},
    # Fallback
    "default":           {"input":  3.00, "cache_write":  3.75, "cache_read": 0.30,  "output": 15.00},
}

def _get_rates(model: str) -> dict[str, float]:
    for prefix, rates in PRICING.items():
        if prefix != "default" and model.startswith(prefix):
            return rates
    return PRICING["default"]

def calc_cost(usage: dict, model: str) -> float:
    """Return estimated $ cost for one turn's usage dict."""
    r = _get_rates(model)
    return (
        usage.get("input_tokens", 0)                * r["input"]       / 1_000_000 +
        usage.get("cache_creation_input_tokens", 0) * r["cache_write"] / 1_000_000 +
        usage.get("cache_read_input_tokens", 0)     * r["cache_read"]  / 1_000_000 +
        usage.get("output_tokens", 0)               * r["output"]      / 1_000_000
    )

def fmt_tok(n: int) -> str:
    """Format token count as compact string."""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)

def fmt_cost(c: float) -> str:
    if c >= 1.0:
        return f"${c:.3f}"
    if c >= 0.001:
        return f"${c:.4f}"
    return f"${c:.5f}"

def cost_color(c: float) -> str:
    """CSS color class based on per-turn cost."""
    if c < 0.01:   return "#3fb950"   # green
    if c < 0.10:   return "#d29922"   # yellow
    if c < 0.50:   return "#f0883e"   # orange
    return "#f85149"                  # red


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAFZElEQVR42r2XTW8bVRSGn3Pv2GO7SZ3ETZp+qKWIVigSXSB1wQ6BwhqxARagigViBb+AX8CSBQs2qBv+AR+iC5CoxAKBgiAVUltoqZw2H26TuI7tmXsPixmPx/Y4rQBha+TxfNz7nnPe855zhOKPASQ9F/79R9PDP+5B+Y82fOL1ZexcBZhfPrMiEct978LQlq1aK+D+0Y6+750x2tMSG617d9bze+UBGEDPnl053trd/Uy9roKYw/wphcYN7ha9gReRbyrl4PLW1u376Qt+BMDs3Kmv1cuqqk9jpaoFS2fwVUGSuyKC6jQA6VNijIi/2t7deCUPwAC+0Tj7bC+Kr6uqAwyCoDqyaTEnFcTg4i6qnqBUQ9UjIqAwWEEQVdQLYsNSaaXVun0dMBnbI/VnMu8KMm7IgMaJT0DxiV1iiaMOs3PPcGz5Ei4+QMRkjkgWA03oJQgaqzszsCYDYIRK5l3VFLmMsVQQY1ILA7zv432Equf8c+8wW38K76PEejT3TTdJ/ohRCfMABtG2I5TRSbqJCC7uEsddXnj5E85deJO43+bCxXe5df1zbvx2hXJ5DvVuNGCaY4YIaozNCw4Adgqp8yxwPqJ65AQrz3/A+s8fs797g9XXvuDR3h227/1AtbaEapyFSwZ+m5C0IcDgydRDEGPpHTzk9Mpl4qjDvTtXKYV1frr2Ifu7tyiH83gfZ1FMaKSjWaGTGTIBQDUl12ABBedjcDG2NMvvv3yKqlKuHgdgZ3MNa8N8cg713NpRlQOQ0bDmAFiUaJhZoqgqYgzHGkvYwIJKSrDEGgVEUlJmFif4nXM8eNAik5RhTIs94HDJIjJE51WphSHVao2dnU1Mhl5yUc65O33Ve2g0jhOW23Q6ncQT2atyeAgYSz4B4riHyAxnz79BGDZItCpdLFFZxAS0d2/S7bZ4sLNGFB0MGZDXUx3h4CQAyUmPIERxxNLiMuWax9kIqQFOx4q1YAyYvsX3HYvHl5mpxrRaLYzI6ObTOVCk3h5rDNaW2Oo2Ofn6aQ4ai6hzQy6kFppyie76Pu6+Y+vaDepSxxpDnDFQCwt9cFgL4b2nVpthb38fs7/D0z9+yUy9hssDSAXLWsP2xkPaex1utprsqaVam6HT2SIYFCwex4Gcu5JapMzNL7Bxr0mVNq/O/0Fj1iJiEWNGwNqSsLa3S7MXsUmb5kaTkydOsLO9lci318JKGYyJQLa5955KpcLRuQUetTtYO8NHXxkCCzs7G8RRP/OCqlIqlanPLxLHIb5yhHpZOFqfp1KtEkdRjrA8xgNprFQ9lcoRol6XY0uLSUgUrLUciQK2tzexqaQ776jXl5idaxBHEWKSzaJ+l0oYstvrEViLFpAgKOhcEpFRxRhD1O8RuzhLTkU5enSW+YUFUJ9qveBcTHv/Ya4xAWuDNOQ6tZcKJhVAc3CSZkPEZO4WoNc9QDkYSVcAY4LUkamKyrCo6hSuB0zr7SSRWWsHi5oUv4KVMa+ZMQt9kpo2SJoTKaoUYwAsFo/L9NyI5aDTptXaHFWynATnwU6EUpOLnc6jlCu5VLQFANTQww1BGiNEUUyz+ddEz1vUpE5rRwNbwhibK82ixph+HoBPGXOHyI3sY0xAaEtZHzjSzOv0yUMLVE2G3YComLuDemdSAOb9995aF/Q7EWvTax7UqXoH6kCdpr9JNUqvqc+OtErk7g2ewyVzgbUifL/64qVfB934yFywcPr8ybjdvaKqL3FYG85hbpjkiqYKICLfztTCt5vNm3fHB5ORFZeWzl2MvD9llDCO3eNnRUvx5GYhEKve0wsCaW5v/7k2Hs3/ezjlsOG0aDz/r8BMHc//Bg8rqxImKmAZAAAAAElFTkSuQmCC">
<style>
  :root {{
    --bg:           #0d1117;
    --bg-card:      #161b22;
    --bg-tool:      #0e1420;
    --bg-result:    #0a1020;
    --border:       #30363d;
    --border-tool:  #1f3a5c;
    --border-result:#1a3a1a;
    --text:         #e6edf3;
    --text-dim:     #8b949e;
    --text-dimmer:  #484f58;
    --user-accent:  #f0883e;
    --asst-accent:  #58a6ff;
    --tool-accent:  #388bfd;
    --result-accent:#3fb950;
    --think-accent: #bc8cff;
    --cost-accent:  #79c0ff;
    --code-bg:      #161b22;
    --font-mono:    "Cascadia Code", "Fira Code", "Consolas", "Menlo", monospace;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.6;
    min-height: 100vh;
  }}

  /* ── Header ── */
  .session-header {{
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    position: sticky;
    top: 0;
    z-index: 100;
  }}
  .session-header .logo {{ color: var(--asst-accent); font-size: 18px; font-weight: bold; letter-spacing: -0.5px; }}
  .session-header .title {{ color: var(--text); font-size: 13px; font-weight: 600; flex: 1; }}
  .session-header .meta  {{ color: var(--text-dim); font-size: 11px; }}

  /* ── Cost panel ── */
  .cost-panel {{
    max-width: 900px;
    margin: 16px auto 0;
    padding: 0 16px;
  }}
  .cost-panel details {{
    border: 1px solid rgba(121,192,255,0.25);
    border-radius: 8px;
    overflow: hidden;
  }}
  .cost-panel summary {{
    padding: 10px 14px;
    background: rgba(121,192,255,0.06);
    color: var(--cost-accent);
    font-size: 12px;
    cursor: pointer;
    user-select: none;
    display: flex;
    align-items: center;
    gap: 12px;
    list-style: none;
  }}
  .cost-panel summary::before {{ content: "▶"; font-size: 9px; color: var(--text-dimmer); margin-right: 4px; }}
  .cost-panel details[open] summary::before {{ content: "▼"; }}
  .cost-total  {{ font-weight: 700; font-size: 14px; }}
  .cost-label  {{ color: var(--text-dim); font-size: 11px; }}
  .cost-body   {{ padding: 14px; border-top: 1px solid rgba(121,192,255,0.15); }}
  .cost-grid   {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 14px; }}
  .cost-cell   {{ background: rgba(0,0,0,0.25); border-radius: 6px; padding: 10px 12px; }}
  .cost-cell .label  {{ font-size: 10px; color: var(--text-dimmer); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
  .cost-cell .value  {{ font-size: 14px; color: var(--text); font-weight: 600; }}
  .cost-cell .sub    {{ font-size: 11px; color: var(--text-dim); margin-top: 2px; }}
  .cost-cell.highlight .value {{ color: var(--cost-accent); }}
  .cost-models {{ font-size: 11px; color: var(--text-dim); }}
  .cost-models span {{ color: var(--text); }}
  .cost-note   {{ margin-top: 8px; font-size: 10px; color: var(--text-dimmer); }}

  /* ── Main layout ── */
  .conversation {{ max-width: 900px; margin: 0 auto; padding: 20px 16px 80px; }}

  /* ── Message ── */
  .message {{
    display: flex;
    gap: 12px;
    padding: 12px 0;
  }}
  .message:not(:last-child) {{ border-bottom: 1px solid var(--border); }}

  .role-badge {{ flex-shrink: 0; width: 72px; text-align: right; padding-top: 1px; }}
  .role-badge span {{
    display: inline-block; padding: 1px 6px; border-radius: 4px;
    font-size: 10px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase;
  }}
  .role-user   .role-badge span {{ background: rgba(240,136,62,0.15); color: var(--user-accent); border: 1px solid rgba(240,136,62,0.3); }}
  .role-asst   .role-badge span {{ background: rgba(88,166,255,0.1);  color: var(--asst-accent); border: 1px solid rgba(88,166,255,0.2); }}
  .role-system .role-badge span {{ background: rgba(139,148,158,0.1); color: var(--text-dim);    border: 1px solid rgba(139,148,158,0.2); }}

  .message-body {{ flex: 1; min-width: 0; }}

  /* ── Message meta row (timestamp + token badge) ── */
  .msg-meta {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 6px;
    flex-wrap: wrap;
  }}
  .timestamp {{ font-size: 10px; color: var(--text-dimmer); }}

  /* ── Token badge ── */
  .token-badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 10px;
    color: var(--text-dimmer);
    background: rgba(0,0,0,0.2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 1px 7px;
    cursor: default;
  }}
  .token-badge .tok-seg {{ white-space: nowrap; }}
  .token-badge .tok-sep {{ color: var(--text-dimmer); opacity: 0.4; }}
  .token-badge .turn-cost {{ font-weight: 700; }}
  .token-badge .cumul {{ color: var(--text-dimmer); }}

  /* ── Text content ── */
  .text-content {{ white-space: pre-wrap; word-break: break-word; }}
  .text-content p    {{ margin: 0 0 8px; }}
  .text-content p:last-child {{ margin-bottom: 0; }}
  .text-content h1,
  .text-content h2,
  .text-content h3 {{ margin: 12px 0 6px; color: var(--text); }}
  .text-content h1 {{ font-size: 16px; }}
  .text-content h2 {{ font-size: 14px; }}
  .text-content h3 {{ font-size: 13px; }}
  .text-content ul,
  .text-content ol {{ margin: 4px 0 8px 20px; }}
  .text-content li  {{ margin: 2px 0; }}
  .text-content a   {{ color: var(--asst-accent); text-decoration: none; }}
  .text-content a:hover {{ text-decoration: underline; }}
  .text-content strong {{ color: #fff; font-weight: 600; }}
  .text-content em     {{ color: #c9d1d9; font-style: italic; }}
  .text-content hr     {{ border: none; border-top: 1px solid var(--border); margin: 12px 0; }}

  .text-content code {{
    background: var(--code-bg); border: 1px solid var(--border); border-radius: 3px;
    padding: 1px 5px; font-family: var(--font-mono); font-size: 12px; color: #f0883e;
  }}
  .text-content pre {{
    background: var(--code-bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 12px; overflow-x: auto; margin: 8px 0; position: relative;
  }}
  .text-content pre code {{ background: none; border: none; padding: 0; color: #e6edf3; font-size: 12px; }}
  .lang-tag {{ position: absolute; top: 6px; right: 8px; font-size: 10px; color: var(--text-dimmer); text-transform: uppercase; }}

  /* ── Thinking block ── */
  .thinking-block {{ margin: 6px 0; border: 1px solid rgba(188,140,255,0.2); border-radius: 6px; overflow: hidden; }}
  .thinking-block summary {{ padding: 6px 10px; background: rgba(188,140,255,0.07); color: var(--think-accent); font-size: 11px; cursor: pointer; user-select: none; list-style: none; }}
  .thinking-block summary::before {{ content: "▶ "; font-size: 9px; }}
  details[open] .thinking-block summary::before {{ content: "▼ "; }}
  .thinking-content {{ padding: 10px; color: var(--text-dim); font-size: 12px; white-space: pre-wrap; word-break: break-word; border-top: 1px solid rgba(188,140,255,0.15); }}

  /* ── Tool call ── */
  .tool-call {{ margin: 6px 0; border: 1px solid var(--border-tool); border-radius: 6px; overflow: hidden; }}
  .tool-call summary {{ padding: 7px 10px; background: var(--bg-tool); color: var(--tool-accent); font-size: 12px; cursor: pointer; user-select: none; display: flex; align-items: center; gap: 8px; list-style: none; }}
  .tool-call summary::before {{ content: "▶"; font-size: 9px; color: var(--text-dimmer); }}
  details[open] .tool-call summary::before {{ content: "▼"; }}
  .tool-name {{ font-weight: 600; color: var(--tool-accent); }}
  .tool-desc {{ color: var(--text-dim); font-size: 11px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .tool-body {{ padding: 10px; background: var(--bg-tool); border-top: 1px solid var(--border-tool); font-size: 12px; }}
  .tool-body pre {{ border-radius: 4px; overflow-x: auto; margin: 0; padding: 0; }}
  .tool-body pre code.hljs {{ border-radius: 4px; font-size: 11px; white-space: pre-wrap; word-break: break-word; }}

  /* ── Subagent inline block ── */
  .subagent-block {{ margin: 10px 0; border: 1px solid var(--border-tool); border-radius: 8px; background: var(--bg-tool); overflow: hidden; }}
  .subagent-block > summary {{ padding: 9px 12px; cursor: pointer; user-select: none; display: flex; align-items: center; gap: 10px; list-style: none; font-size: 12px; border-bottom: 1px solid transparent; }}
  .subagent-block[open] > summary {{ border-bottom-color: var(--border-tool); }}
  .subagent-block > summary::before {{ content: "▶"; font-size: 9px; color: var(--text-dimmer); }}
  .subagent-block[open] > summary::before {{ content: "▼"; }}
  .sa-badge {{ display: inline-block; padding: 2px 7px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; background: var(--tool-accent); color: var(--bg); border-radius: 3px; }}
  .sa-type {{ font-weight: 600; color: var(--tool-accent); font-family: var(--font-mono); font-size: 11px; }}
  .sa-desc {{ flex: 1; color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .sa-stats {{ color: var(--text-dim); font-family: var(--font-mono); font-size: 10.5px; flex-shrink: 0; }}
  .sa-body {{ padding: 4px 14px 10px; border-left: 2px solid var(--tool-accent); margin: 0 10px 10px; background: var(--bg); border-radius: 0 0 6px 6px; }}
  .sa-body .message {{ margin: 8px 0; }}

  /* ── Tool result ── */
  .tool-result {{ margin: 6px 0; border: 1px solid var(--border-result); border-radius: 6px; overflow: hidden; }}
  .tool-result summary {{ padding: 7px 10px; background: var(--bg-result); color: var(--result-accent); font-size: 11px; cursor: pointer; user-select: none; list-style: none; }}
  .tool-result summary::before {{ content: "▶ "; font-size: 9px; color: var(--text-dimmer); }}
  details[open] .tool-result summary::before {{ content: "▼ "; }}
  .result-body {{ padding: 10px; background: var(--bg-result); border-top: 1px solid var(--border-result); color: var(--text-dim); font-size: 11px; white-space: pre-wrap; word-break: break-word; max-height: 400px; overflow-y: auto; }}

  /* ── Image ── */
  .inline-image {{ max-width: 100%; border-radius: 6px; border: 1px solid var(--border); margin: 6px 0; display: block; }}

  /* ── Stats bar ── */
  .stats-bar {{
    background: var(--bg-card); border-top: 1px solid var(--border);
    padding: 10px 24px; display: flex; gap: 20px; font-size: 11px;
    color: var(--text-dim); position: sticky; bottom: 0; flex-wrap: wrap;
  }}
  .stats-bar span {{ color: var(--text); }}
  .stats-bar .total-cost {{ color: var(--cost-accent); font-weight: 700; }}

  /* ── Slash command block ── */
  .slash-command {{
    display: inline-flex;
    align-items: baseline;
    gap: 8px;
    padding: 4px 10px;
    background: rgba(240,136,62,0.07);
    border: 1px solid rgba(240,136,62,0.22);
    border-radius: 6px;
    font-size: 12px;
    font-family: var(--font-mono);
    flex-wrap: wrap;
  }}
  .slash-cmd-name {{ color: var(--user-accent); font-weight: 700; }}
  .slash-cmd-msg  {{ color: var(--text-dim); }}
  .slash-cmd-args {{ color: var(--text-dimmer); font-style: italic; }}

  /* ── System output blocks (local-command-stdout, system-reminder, etc.) ── */
  .sys-block {{
    display: flex;
    align-items: flex-start;
    gap: 7px;
    padding: 4px 9px;
    background: rgba(0,0,0,0.18);
    border: 1px solid rgba(139,148,158,0.12);
    border-radius: 4px;
    font-size: 11px;
    color: var(--text-dimmer);
    font-family: var(--font-mono);
    line-height: 1.5;
  }}
  .sys-icon {{ flex-shrink: 0; opacity: 0.45; font-size: 10px; padding-top: 1px; }}
  .sys-text  {{ word-break: break-word; flex: 1; }}
  .sys-stderr {{ border-color: rgba(248,81,73,0.18); color: rgba(248,81,73,0.7); }}
  .sys-reminder {{ border-color: rgba(88,166,255,0.12); color: rgba(88,166,255,0.55); }}

  /* ── Interrupt bar ── */
  .interrupt-badge {{
    display: block;
    width: 100%;
    font-size: 11px;
    font-weight: 600;
    color: #f85149;
    background: rgba(248,81,73,0.08);
    border: 1px solid rgba(248,81,73,0.25);
    border-left: 3px solid rgba(248,81,73,0.7);
    border-radius: 4px;
    padding: 5px 10px;
    letter-spacing: 0.2px;
  }}

  /* ── AskUserQuestion card ── */
  .ask-container {{ margin: 6px 0; display: flex; flex-direction: column; gap: 8px; }}
  .ask-card {{
    border: 1px solid rgba(188,140,255,0.22);
    border-radius: 6px;
    background: rgba(188,140,255,0.05);
    padding: 10px 14px;
    display: flex;
    flex-direction: column;
    gap: 7px;
  }}
  .ask-header {{
    font-size: 10px;
    font-weight: 700;
    color: var(--think-accent);
    text-transform: uppercase;
    letter-spacing: 0.6px;
  }}
  .ask-question {{
    font-size: 13px;
    color: var(--text);
    line-height: 1.45;
  }}
  .ask-options {{
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .ask-option {{
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 4px 8px;
    background: rgba(0,0,0,0.18);
    border: 1px solid rgba(188,140,255,0.1);
    border-radius: 4px;
  }}
  .ask-opt-label {{
    font-size: 12px;
    color: var(--text-dim);
    font-weight: 500;
  }}
  .ask-opt-label::before {{ content: "◦ "; color: var(--think-accent); opacity: 0.7; }}
  .ask-opt-desc  {{ font-size: 11px; color: var(--text-dimmer); font-style: italic; padding-left: 12px; }}
  .ask-multi-note {{ font-size: 10px; color: var(--text-dimmer); font-style: italic; }}

  /* ── Markdown tables ── */
  .md-table-wrap {{
    overflow-x: auto;
    margin: 10px 0;
    border-radius: 6px;
    border: 1px solid var(--border);
  }}
  .md-table {{
    border-collapse: collapse;
    width: 100%;
    font-size: 12px;
    font-family: var(--font-mono);
  }}
  .md-table th {{
    background: rgba(0,0,0,0.3);
    color: var(--text);
    font-weight: 600;
    text-align: left;
    padding: 6px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  .md-table td {{
    padding: 5px 12px;
    border-bottom: 1px solid rgba(48,54,61,0.6);
    color: var(--text-dim);
    vertical-align: top;
  }}
  .md-table tr:last-child td {{ border-bottom: none; }}
  .md-table tr:nth-child(even) td {{ background: rgba(0,0,0,0.12); }}

  ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  ::-webkit-scrollbar-track {{ background: var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}

  /* ── Copy button ── */
  .code-wrap {{ position: relative; display: block; margin: 8px 0; }}
  .text-content .code-wrap {{ margin: 8px 0; }}
  .tool-body .code-wrap {{ margin: 0; }}
  .copy-btn {{
    position: absolute; top: 6px; right: 8px;
    background: rgba(30,36,44,0.92); border: 1px solid var(--border);
    border-radius: 3px; color: var(--text-dimmer); font-size: 10px;
    padding: 2px 7px; cursor: pointer; opacity: 0; transition: opacity 0.15s;
    font-family: var(--font-mono); line-height: 1.5; z-index: 10;
  }}
  .code-wrap:hover .copy-btn {{ opacity: 1; }}
  .copy-btn:hover {{ color: var(--text); background: rgba(88,166,255,0.12); border-color: var(--asst-accent); }}
  .copy-btn.copied {{ color: #3fb950; border-color: rgba(63,185,80,0.4); opacity: 1; }}

  /* ── Diff view ── */
  .diff-view {{ font-family: var(--font-mono); font-size: 11px; overflow-x: auto; }}
  .diff-file {{ padding: 4px 10px; background: rgba(0,0,0,0.35); color: var(--text-dimmer); font-size: 10px; border-bottom: 1px solid var(--border-tool); letter-spacing: 0.3px; }}
  .diff-hunk {{ color: rgba(88,166,255,0.55); padding: 1px 10px; font-size: 10px; background: rgba(88,166,255,0.04); border-bottom: 1px solid rgba(88,166,255,0.1); }}
  .diff-line {{ display: flex; min-height: 17px; }}
  .diff-line-add  {{ background: rgba(63,185,80,0.1); }}
  .diff-line-del  {{ background: rgba(248,81,73,0.1); }}
  .diff-sign {{ width: 18px; text-align: center; flex-shrink: 0; padding: 1px 0; font-weight: 700; font-size: 12px; }}
  .diff-line-add .diff-sign  {{ color: #3fb950; }}
  .diff-line-del .diff-sign  {{ color: #f85149; }}
  .diff-line-ctx .diff-sign  {{ color: var(--text-dimmer); opacity: 0.4; }}
  .diff-text {{ white-space: pre-wrap; word-break: break-word; padding: 1px 8px; flex: 1; }}
  .diff-line-add .diff-text  {{ color: #7ee787; }}
  .diff-line-del .diff-text  {{ color: #ffa198; }}
  .diff-line-ctx .diff-text  {{ color: var(--text-dimmer); }}
  .diff-no-change {{ padding: 6px 10px; color: var(--text-dimmer); font-size: 10px; font-style: italic; }}
  .write-content {{ padding: 0; }}

  /* ── Tool ribbon ── */
  .tool-ribbon {{
    display: flex; flex-wrap: wrap; gap: 4px; margin: 3px 0 5px;
    font-size: 10px;
  }}
  .tool-chip {{
    padding: 1px 6px; border-radius: 3px;
    background: rgba(56,139,253,0.08); border: 1px solid rgba(56,139,253,0.18);
    color: var(--tool-accent); white-space: nowrap; cursor: default;
  }}

  /* ── Timing delta ── */
  .timing-delta {{ font-size: 10px; color: var(--text-dimmer); font-style: italic; margin-top: 4px; }}

  /* ── Message anchor ── */
  .msg-anchor {{
    font-size: 10px; color: var(--text-dimmer); text-decoration: none;
    opacity: 0; transition: opacity 0.15s; margin-left: 4px; font-weight: normal;
  }}
  .message:hover .msg-anchor {{ opacity: 0.45; }}
  .msg-anchor:hover {{ opacity: 1 !important; color: var(--asst-accent); }}

  /* ── Expand-all button ── */
  .expand-all-btn {{
    padding: 3px 10px; border-radius: 4px; font-size: 10px;
    background: rgba(56,139,253,0.1); border: 1px solid rgba(56,139,253,0.2);
    color: var(--asst-accent); cursor: pointer; font-family: var(--font-mono);
    white-space: nowrap; flex-shrink: 0;
  }}
  .expand-all-btn:hover {{ background: rgba(56,139,253,0.2); }}

  /* ── Scroll to top ── */
  #scroll-top {{
    position: fixed; bottom: 52px; right: 18px;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 6px; padding: 5px 10px; font-size: 11px;
    color: var(--text-dim); cursor: pointer; opacity: 0;
    transition: opacity 0.2s; z-index: 200; font-family: var(--font-mono);
  }}
  #scroll-top.visible {{ opacity: 0.85; }}
  #scroll-top:hover {{ opacity: 1; color: var(--text); border-color: var(--asst-accent); }}

  /* ── WebSearch result cards ── */
  .ws-results {{ display: flex; flex-direction: column; gap: 7px; padding: 10px; background: var(--bg-result); border-top: 1px solid var(--border-result); }}
  .ws-card {{ border: 1px solid rgba(48,54,61,0.7); border-radius: 6px; padding: 8px 12px; background: rgba(0,0,0,0.18); }}
  .ws-title {{ font-size: 12px; color: var(--asst-accent); font-weight: 600; margin-bottom: 2px; }}
  .ws-url {{ font-size: 10px; color: var(--text-dimmer); margin-bottom: 4px; word-break: break-all; }}
  .ws-desc {{ font-size: 11px; color: var(--text-dim); line-height: 1.45; white-space: pre-wrap; word-break: break-word; }}

  /* ── Mermaid diagrams ── */
  .mermaid {{ margin: 8px 0; background: rgba(0,0,0,0.2); border: 1px solid var(--border); border-radius: 6px; padding: 16px; overflow-x: auto; text-align: center; }}
  .mermaid svg {{ max-width: 100%; }}
</style>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/vs2015.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<script>
  if (typeof mermaid !== 'undefined') {{
    mermaid.initialize({{startOnLoad: false, theme: 'dark', securityLevel: 'loose',
      themeVariables: {{background: '#0d1117', primaryColor: '#1f3a5c', lineColor: '#58a6ff',
        textColor: '#e6edf3', edgeLabelBackground: '#161b22'}}}});
  }}

  document.addEventListener('DOMContentLoaded', function() {{
    // Syntax highlighting
    document.querySelectorAll('pre code[class*="language-"]').forEach(function(el) {{
      hljs.highlightElement(el);
    }});

    // Mermaid diagrams
    if (typeof mermaid !== 'undefined') {{
      mermaid.run({{nodes: document.querySelectorAll('.mermaid')}});
    }}

    // Copy buttons — wrap every <pre> that isn't already wrapped
    document.querySelectorAll('pre').forEach(function(pre) {{
      if (pre.parentNode.classList.contains('code-wrap')) return;
      var wrap = document.createElement('div');
      wrap.className = 'code-wrap';
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
      var btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.textContent = 'copy';
      btn.addEventListener('click', function(ev) {{
        ev.stopPropagation();
        var code = pre.querySelector('code');
        var text = code ? (code.innerText || code.textContent) : (pre.innerText || pre.textContent);
        if (navigator.clipboard) {{
          navigator.clipboard.writeText(text).then(function() {{
            btn.textContent = 'copied!'; btn.classList.add('copied');
            setTimeout(function() {{ btn.textContent = 'copy'; btn.classList.remove('copied'); }}, 1500);
          }}).catch(function() {{ btn.textContent = 'error'; setTimeout(function() {{ btn.textContent = 'copy'; }}, 1500); }});
        }} else {{
          // Fallback for browsers without clipboard API
          var ta = document.createElement('textarea');
          ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
          document.body.appendChild(ta); ta.select();
          try {{ document.execCommand('copy'); btn.textContent = 'copied!'; btn.classList.add('copied');
            setTimeout(function() {{ btn.textContent = 'copy'; btn.classList.remove('copied'); }}, 1500);
          }} catch(e) {{ btn.textContent = 'error'; setTimeout(function() {{ btn.textContent = 'copy'; }}, 1500); }}
          document.body.removeChild(ta);
        }}
      }});
      wrap.appendChild(btn);
    }});

    // Expand/collapse all tool calls
    var expandBtn = document.getElementById('expand-all-btn');
    if (expandBtn) {{
      expandBtn.addEventListener('click', function() {{
        var details = document.querySelectorAll('details.tool-call');
        var anyOpen = Array.from(details).some(function(d) {{ return d.open; }});
        details.forEach(function(d) {{ d.open = !anyOpen; }});
        expandBtn.textContent = anyOpen ? '▶ expand all' : '▼ collapse all';
      }});
    }}

    // Scroll-to-top button
    var scrollBtn = document.getElementById('scroll-top');
    if (scrollBtn) {{
      window.addEventListener('scroll', function() {{
        scrollBtn.classList.toggle('visible', window.scrollY > 300);
      }});
      scrollBtn.addEventListener('click', function() {{
        window.scrollTo({{top: 0, behavior: 'smooth'}});
      }});
    }}
  }});
</script>
</head>
<body>

<div class="session-header">
  <div class="logo" style="display:flex;align-items:center;gap:8px"><img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAD1ElEQVR42q2Wz24bVRTGf+feO+MxTeKkSZsGwgbMAgTdREJILCrYwIYXQAIWhX3Fe9BnQIgFLwEqSyQqgSpQkIIIaUnc1H+SOvGM7bn3sJjxn3ECAsGxbF+PR+fc833n++7ALASw/PewZa5p0krcunXL7e7u1lZXVw2sA51/lPXkpBa2t6PR/fv3xyzsWgCazebycTu9G4K+DSSKOCMQ9C8yCqCUH4KgHiUVK99Epv5pt7vXB3CAAfzjdnpX1dxW9SCgGghaNKhz+SbfGjwitvxdvAQBldvDfADwMWAN4Hd2dqLg9R0N3gM5qgqooqrM1oIqIqrqNa6taNmfSvlWNA8heFTf3dnZiQBvAPb3zxIRYgQLakEm0IkgAioiRoyNJD1vybWtN+T5F94TP05FxAio6HRI1CpE+/tnyQQiGo2xedxWi0oJQ9GuoogYRlmXF1/5kFqyTvfJD0TxMr/+/AUuuoKqr0BX8mMbjbHpdAr8q8RNMJ4kH/V56bVPSAfH/PbLV2zceJ2j379GxFb4qUSAXrl089cL6GdrVY91Ca2H98jSNsGP+On7z3DREmAJBT3l5qpl1iiKVAqgxX0hBJJ6neWVBvk4JfgeSSMBeaaATgOIQcTgXI3+06ekWYoRU6ZRer1LOhCRckSVpJYwyjJctM3S0iYachBBVRER8vycdNAm+D5xLWYwOAdn5oi4pEC1mcDG9S3c6ptcvXETnw+LDQBiIwanj+i2HlA3jzg+2i9a10l+rRboLfAcVKnFCXk+pv/yGdw8I8+yaQHjHKNWytmDFHcwJo4TNJwg1hZquNBBb5ZdS2m7OOZx6w/e733Lq0cPCEEQEVQhcsLDdp8f+12+O8q4snxtWnxxpqocIIQQiJOE5aUG6fk5uwdweNyl1+2U9IE1QlRf42RQI4oNyysrJJ06o/GoKKSLBdaA9mwC4ijCWsPWs9u0BsrhAHpdZTwujDKKIjY2NhBRrm8WWneRYzjMMNahixxU2S1EPxoNCcEjCE7guc2rczDAcJihKMNcMcbOEauXQDTlQKZQRVGNEPzUBHIfKmBaF5d2EjDGFE46CbNQYG0NnnRQVcUYQ5altI4O5gjTC0qddVv4aJZlZSeFaU+k7ACSJElVhyPAiwghqOl2O/MCr5iZXNAMOBshIqEQIvm6MVlv7hz2K43tzxXzkaqfqfoyAZZ+tfj/7LpB8V+enR5+AFhXeB8iq/YOJx5E3gKtB1Uzf4oVFnJxGCY3iBBUSQW9ZxruDqeFZi9ss9ls1oBapxPk3zxKrK8bBYZ7e3tD/uYY/98fW/4Ex+zZrTZ+m9IAAAAASUVORK5CYII=" width="24" height="24" alt="" style="border-radius:5px;flex-shrink:0">Claude Code</div>
  <div class="title">{title}</div>
  <div class="meta">{meta}</div>
  <button class="expand-all-btn" id="expand-all-btn">▼ collapse all</button>
</div>

{cost_panel_html}

<div class="conversation">
{messages_html}
</div>

<div class="stats-bar">
  <div>Messages: <span>{msg_count}</span></div>
  <div>User turns: <span>{user_turns}</span></div>
  <div>Assistant turns: <span>{asst_turns}</span></div>
  <div>Tool calls: <span>{tool_calls}</span></div>
  <div>Tokens: <span>{total_tokens}</span></div>
  <div>Duration: <span>{duration_str}</span></div>
  <div>Est. cost: <span class="total-cost">{total_cost_str}</span></div>
  <div>Session: <span>{session_id}</span></div>
</div>

<button id="scroll-top" title="Back to top">↑ top</button>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Markdown-to-HTML (no dependencies)
# ---------------------------------------------------------------------------

def md_to_html(text: str) -> str:
    if not text:
        return ""

    lines = text.split('\n')
    out = []
    i = 0

    def escape(s: str) -> str:
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

    def inline(s: str) -> str:
        result = ''
        while s:
            m = re.match(r'`([^`]+)`', s)
            if m:
                result += f'<code>{escape(m.group(1))}</code>'
                s = s[m.end():]
                continue
            m = re.match(r'\*\*\*(.+?)\*\*\*', s)
            if m:
                result += f'<strong><em>{escape(m.group(1))}</em></strong>'
                s = s[m.end():]
                continue
            m = re.match(r'\*\*(.+?)\*\*', s)
            if m:
                result += f'<strong>{escape(m.group(1))}</strong>'
                s = s[m.end():]
                continue
            m = re.match(r'\*(.+?)\*', s)
            if m:
                result += f'<em>{escape(m.group(1))}</em>'
                s = s[m.end():]
                continue
            m = re.match(r'\[([^\]]+)\]\(([^\)]+)\)', s)
            if m:
                result += f'<a href="{escape(m.group(2))}" target="_blank">{escape(m.group(1))}</a>'
                s = s[m.end():]
                continue
            result += escape(s[0])
            s = s[1:]
        return result

    def is_table_row(s: str) -> bool:
        return bool(re.match(r'^\s*\|', s))

    def is_sep_row(cells: list) -> bool:
        return bool(cells) and all(re.match(r'^[-: ]+$', c) for c in cells if c.strip())

    def split_cells(row: str) -> list:
        return [c.strip() for c in row.strip().lstrip('|').rstrip('|').split('|')]

    def render_table(tlines: list) -> str:
        rows = [split_cells(l) for l in tlines]
        if not rows:
            return ''
        has_header = len(rows) >= 2 and is_sep_row(rows[1])
        parts = ['<div class="md-table-wrap"><table class="md-table">']
        if has_header:
            parts.append('<thead><tr>')
            for cell in rows[0]:
                parts.append(f'<th>{inline(escape(cell))}</th>')
            parts.append('</tr></thead><tbody>')
            body = rows[2:]
        else:
            parts.append('<tbody>')
            body = rows
        for row in body:
            if is_sep_row(row):
                continue
            parts.append('<tr>')
            for cell in row:
                parts.append(f'<td>{inline(escape(cell))}</td>')
            parts.append('</tr>')
        parts.append('</tbody></table></div>')
        return ''.join(parts)

    while i < len(lines):
        line = lines[i]
        m = re.match(r'^```(\w*)', line)
        if m:
            lang = m.group(1)
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                code_lines.append(lines[i])
                i += 1
            if lang == 'mermaid':
                # Mermaid diagrams: pass raw text to mermaid.js (no HTML escaping)
                out.append(f'<div class="mermaid">{chr(10).join(code_lines)}</div>')
            else:
                esc_lines = [escape(l) for l in code_lines]
                lang_tag  = f'<span class="lang-tag">{escape(lang)}</span>' if lang else ''
                lang_attr = f' class="language-{escape(lang)}"' if lang else ''
                out.append(f'<pre>{lang_tag}<code{lang_attr}>{chr(10).join(esc_lines)}</code></pre>')
            i += 1
            continue
        # Markdown table — collect pipe rows, tolerating blank lines between them
        if is_table_row(line):
            tlines = []
            j = i
            while j < len(lines):
                if is_table_row(lines[j]):
                    tlines.append(lines[j])
                    j += 1
                elif not lines[j].strip():
                    # peek ahead: if next non-blank line is also a table row, keep going
                    k = j + 1
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    if k < len(lines) and is_table_row(lines[k]):
                        j = k  # skip the blank(s) and continue collecting
                    else:
                        break
                else:
                    break
            i = j
            out.append(render_table(tlines))
            continue
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            level = len(m.group(1))
            out.append(f'<h{level}>{inline(m.group(2))}</h{level}>')
            i += 1
            continue
        if re.match(r'^---+$', line) or re.match(r'^\*\*\*+$', line):
            out.append('<hr>')
            i += 1
            continue
        m = re.match(r'^(\s*)[*\-+]\s+(.*)', line)
        if m:
            items = [inline(m.group(2))]
            i += 1
            while i < len(lines):
                m2 = re.match(r'^(\s*)[*\-+]\s+(.*)', lines[i])
                if m2:
                    items.append(inline(m2.group(2)))
                    i += 1
                else:
                    break
            out.append('<ul>' + ''.join(f'<li>{it}</li>' for it in items) + '</ul>')
            continue
        m = re.match(r'^(\s*)\d+\.\s+(.*)', line)
        if m:
            items = [inline(m.group(2))]
            i += 1
            while i < len(lines):
                m2 = re.match(r'^(\s*)\d+\.\s+(.*)', lines[i])
                if m2:
                    items.append(inline(m2.group(2)))
                    i += 1
                else:
                    break
            out.append('<ol>' + ''.join(f'<li>{it}</li>' for it in items) + '</ol>')
            continue
        if line.strip() == '':
            out.append('')
            i += 1
            continue
        # Interrupt / system notice
        stripped = line.strip()
        if stripped.startswith('[Request interrupted') or stripped.startswith('[Interrupted by user'):
            label = stripped.strip('[]')
            out.append(f'<span class="interrupt-badge">↩ {escape(label)}</span>')
            i += 1
            continue
        out.append(f'<p>{inline(line)}</p>')
        i += 1

    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Content block renderers
# ---------------------------------------------------------------------------

# System-injected wrapper tags → (icon, css-class-suffix)
_SYSTEM_TAGS = {
    'local-command-stdout':    ('$',  'stdout'),
    'local-command-stderr':    ('⚠',  'stderr'),
    'system-reminder':         ('◆',  'reminder'),
    'user-prompt-submit-hook': ('⚙',  'hook'),
    'bash-stdout':             ('$',  'stdout'),
    'bash-stderr':             ('⚠',  'stderr'),
}

def try_render_system_block(text: str):
    """
    If text is entirely a system-injected wrapper tag (<local-command-stdout> etc.),
    render it as a styled dim system block; else return None.
    """
    stripped = text.strip()
    for tag, (icon, suffix) in _SYSTEM_TAGS.items():
        m = re.match(
            rf'^<{re.escape(tag)}>(.*?)</{re.escape(tag)}>$',
            stripped, re.DOTALL
        )
        if m:
            def e(s): return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            content = e(m.group(1).strip())
            if not content:
                return ''   # suppress empty system blocks (e.g. empty local-command-stdout)
            return (
                f'<div class="sys-block sys-{suffix}">'
                f'<span class="sys-icon">{icon}</span>'
                f'<span class="sys-text">{content}</span>'
                f'</div>'
            )
    return None


def try_render_slash_command(text: str):
    """
    If text is a Claude Code slash command invocation
    (<command-name>...</command-name>...), return styled HTML; else return None.
    Tags may appear in any order.
    """
    stripped = text.strip()
    # Require at least one recognized slash-command tag to be present
    if '<command-name>' not in stripped and '<command-message>' not in stripped:
        return None

    def esc(s):
        return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def extract(tag):
        m = re.search(rf'<{re.escape(tag)}>(.*?)</{re.escape(tag)}>', stripped, re.DOTALL)
        return (m.group(1) or '').strip() if m else ''

    name = esc(extract('command-name'))
    msg  = esc(extract('command-message'))
    args = esc(extract('command-args'))

    if not name and not msg:
        return None

    # Use message as display name when command-name is absent (shouldn't happen, but safe)
    display_name = name or msg

    inner = f'<span class="slash-cmd-name">{display_name}</span>'
    if msg and msg != display_name:
        inner += f'<span class="slash-cmd-msg">{msg}</span>'
    if args and args != display_name:
        inner += f'<span class="slash-cmd-args">{args}</span>'

    return f'<div class="slash-command">{inner}</div>'


def render_text_block(text: str) -> str:
    cmd = try_render_slash_command(text)
    if cmd:
        return cmd
    sys_block = try_render_system_block(text)
    if sys_block is not None:
        return sys_block
    return f'<div class="text-content">{md_to_html(text)}</div>'


def render_thinking_block(thinking: str) -> str:
    if not thinking:
        return ''
    esc = thinking.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return (
        f'<details class="thinking-block">'
        f'<summary>Thinking</summary>'
        f'<div class="thinking-content">{esc}</div>'
        f'</details>'
    )


def _e(s) -> str:
    """Module-level HTML escape helper."""
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def render_ask_user_question(inp: dict, tool_id: str, tool_map: dict) -> str:
    """Render AskUserQuestion tool call as a styled question card."""
    questions = inp.get('questions', [])
    if not questions:
        questions = [inp]  # sometimes the whole input is one question

    cards = []
    for q in questions:
        header   = (q.get('header')   or '').strip()
        question = (q.get('question') or '').strip()
        multi    = q.get('multiSelect', False)
        options  = q.get('options', [])

        parts = ['<div class="ask-card">']
        if header:
            parts.append(f'<div class="ask-header">❓ {_e(header)}</div>')
        if question:
            parts.append(f'<div class="ask-question">{_e(question)}</div>')
        if options:
            parts.append('<div class="ask-options">')
            for opt in options:
                if isinstance(opt, dict):
                    label = (opt.get('label') or '').strip()
                    desc  = (opt.get('description') or '').strip()
                elif isinstance(opt, str):
                    label, desc = opt, ''
                else:
                    continue
                parts.append(
                    f'<div class="ask-option">'
                    f'<span class="ask-opt-label">{_e(label)}</span>'
                    + (f'<span class="ask-opt-desc">{_e(desc)}</span>' if desc else '')
                    + '</div>'
                )
            parts.append('</div>')
        if multi:
            parts.append('<div class="ask-multi-note">↳ multiple selections allowed</div>')
        parts.append('</div>')
        cards.append(''.join(parts))

    result_html = render_tool_result_inline(tool_map[tool_id]) if tool_id in tool_map else ''
    return '<div class="ask-container">' + ''.join(cards) + '</div>' + result_html


def render_edit_diff(inp: dict, esc_name: str, esc_desc: str, result_html: str) -> str:
    """Render Edit tool call as a line-by-line diff."""
    file_path = inp.get('file_path', '')
    old_str   = inp.get('old_string', '')
    new_str   = inp.get('new_string', '')

    old_lines = old_str.splitlines(keepends=True)
    new_lines = new_str.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=3))

    rows = []
    for dl in diff_lines[:400]:  # cap at 400 diff lines
        if dl.startswith('---') or dl.startswith('+++'):
            continue
        if dl.startswith('@@'):
            rows.append(f'<div class="diff-hunk">{_e(dl)}</div>')
        elif dl.startswith('+'):
            rows.append(
                f'<div class="diff-line diff-line-add">'
                f'<span class="diff-sign">+</span>'
                f'<span class="diff-text">{_e(dl[1:])}</span></div>'
            )
        elif dl.startswith('-'):
            rows.append(
                f'<div class="diff-line diff-line-del">'
                f'<span class="diff-sign">-</span>'
                f'<span class="diff-text">{_e(dl[1:])}</span></div>'
            )
        else:
            text = dl[1:] if dl.startswith(' ') else dl
            rows.append(
                f'<div class="diff-line diff-line-ctx">'
                f'<span class="diff-sign"> </span>'
                f'<span class="diff-text">{_e(text)}</span></div>'
            )

    if not rows:
        rows = [f'<div class="diff-no-change">No changes detected</div>']

    diff_body = '\n'.join(rows)
    return (
        f'<details class="tool-call" open>'
        f'<summary><span class="tool-name">{esc_name}</span>'
        f'<span class="tool-desc">{esc_desc}</span></summary>'
        f'<div class="tool-body diff-view">'
        f'<div class="diff-file">{_e(file_path)}</div>'
        f'{diff_body}'
        f'</div>'
        f'</details>'
        + result_html
    )


def render_write_block(inp: dict, esc_name: str, esc_desc: str, result_html: str) -> str:
    """Render Write tool call with syntax-highlighted content."""
    file_path = inp.get('file_path', '')
    content   = inp.get('content', '')

    ext = Path(file_path).suffix.lstrip('.').lower()
    LANG_MAP = {
        'py': 'python', 'js': 'javascript', 'ts': 'typescript',
        'tsx': 'typescript', 'jsx': 'javascript', 'html': 'html',
        'css': 'css', 'json': 'json', 'md': 'markdown',
        'sh': 'bash', 'bash': 'bash', 'yml': 'yaml', 'yaml': 'yaml',
        'rs': 'rust', 'go': 'go', 'java': 'java', 'cpp': 'cpp',
        'c': 'c', 'cs': 'csharp', 'rb': 'ruby', 'php': 'php',
        'toml': 'ini', 'ini': 'ini', 'xml': 'xml', 'sql': 'sql',
    }
    lang = LANG_MAP.get(ext, '')
    lang_attr = f' class="language-{lang}"' if lang else ''
    return (
        f'<details class="tool-call" open>'
        f'<summary><span class="tool-name">{esc_name}</span>'
        f'<span class="tool-desc">{esc_desc}</span></summary>'
        f'<div class="tool-body write-content diff-view">'
        f'<div class="diff-file">{_e(file_path)}</div>'
        f'<pre><code{lang_attr}>{_e(content)}</code></pre>'
        f'</div>'
        f'</details>'
        + result_html
    )


def _try_render_web_search(content) -> str:
    """Try to parse WebSearch result as styled cards; return '' if not parseable."""
    text = ''
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        for cb in content:
            if isinstance(cb, dict) and cb.get('type') == 'text':
                text += cb.get('text', '')

    if not text:
        return ''

    records = []

    # ── Attempt 1: JSON (Bing/custom API format) ──────────────────────────────
    try:
        data = json.loads(text)
        raw_list = []
        if isinstance(data, list):
            raw_list = data
        elif isinstance(data, dict):
            for key in ('results', 'Results', 'links', 'Links', 'items', 'webPages'):
                val = data.get(key)
                if isinstance(val, list):
                    raw_list = val
                    break
                if isinstance(val, dict) and 'value' in val:
                    raw_list = val['value']
                    break
        for r in raw_list:
            if not isinstance(r, dict):
                continue
            title = r.get('title', r.get('Title', r.get('name', '')))
            url   = r.get('url', r.get('URL', r.get('link', r.get('Link', r.get('displayUrl', '')))))
            desc  = r.get('description', r.get('Description',
                    r.get('snippet', r.get('Snippet', r.get('body', r.get('Body', ''))))))
            if title or url:
                records.append({'title': str(title), 'url': str(url), 'desc': str(desc)[:600]})
    except (json.JSONDecodeError, TypeError):
        pass

    # ── Attempt 2: Brave Search plain-text format (Title:/URL:/Body: lines) ───
    if not records and ('Title:' in text or 'URL:' in text):
        current: dict = {}
        for line in text.split('\n'):
            stripped = line.strip()
            if not stripped:
                if current:
                    records.append(current)
                    current = {}
                continue
            low = stripped.lower()
            if low.startswith('title:'):
                if current.get('title') and current.get('url'):
                    records.append(current)
                current = {'title': stripped[6:].strip(), 'url': '', 'desc': ''}
            elif low.startswith('url:'):
                current['url'] = stripped[4:].strip()
            elif low.startswith('body:') or low.startswith('description:') or low.startswith('snippet:'):
                sep = stripped.index(':')
                current['desc'] = stripped[sep + 1:].strip()
            elif low.startswith('age:') or low.startswith('page age:'):
                pass  # skip metadata
        if current.get('title') or current.get('url'):
            records.append(current)

    if not records:
        return ''

    # Extract query from header line "Web search results for query: "...""
    query = ''
    m = re.search(r'[Ww]eb search results for query[:\s]+"?([^"\n]+)"?', text)
    if m:
        query = m.group(1).strip().strip('"')

    cards = []
    for r in records[:12]:
        title = r.get('title', '')
        url   = r.get('url', '')
        desc  = r.get('desc', '')
        if not (title or url):
            continue
        card = '<div class="ws-card">'
        if title:
            card += f'<div class="ws-title">{_e(title)}</div>'
        if url:
            card += f'<div class="ws-url">{_e(url)}</div>'
        if desc:
            card += f'<div class="ws-desc">{_e(desc)}</div>'
        card += '</div>'
        cards.append(card)

    if not cards:
        return ''

    q_str = f' for &ldquo;{_e(query)}&rdquo;' if query else ''
    header = f'<summary>WebSearch — {len(cards)} results{q_str}</summary>'
    return (
        f'<details class="tool-result" open>'
        + header
        + f'<div class="ws-results">{"".join(cards)}</div>'
        f'</details>'
    )


def render_tool_use_block(block: dict, tool_map: dict) -> str:
    name    = block.get('name', 'unknown')
    tool_id = block.get('id', '')
    inp     = block.get('input', {})

    # Dedicated renderer for interactive prompts
    if name == 'AskUserQuestion':
        return render_ask_user_question(inp, tool_id, tool_map)

    # Agent tool → inline the subagent transcript if we have one loaded
    if name == 'Agent':
        agent_id = _agent_id_by_tool.get(tool_id)
        if agent_id and agent_id in _subagent_entries:
            return render_subagent_block(agent_id, inp, tool_map.get(tool_id))

    desc = ''
    for key in ('command', 'file_path', 'pattern', 'path', 'query', 'skill', 'prompt'):
        if key in inp:
            desc = str(inp[key])[:80]
            break

    esc_name = _e(name)
    esc_desc = _e(desc)

    result_html = render_tool_result_inline(tool_map[tool_id], tool_name=name) if tool_id in tool_map else ''

    # Diff view for Edit tool
    if name == 'Edit' and 'old_string' in inp and 'new_string' in inp:
        return render_edit_diff(inp, esc_name, esc_desc, result_html)

    # Syntax-highlighted content for Write tool
    if name == 'Write' and 'content' in inp:
        return render_write_block(inp, esc_name, esc_desc, result_html)

    try:
        inp_str = json.dumps(inp, indent=2, ensure_ascii=False)
    except Exception:
        inp_str = str(inp)

    esc_inp = _e(inp_str)

    return (
        f'<details class="tool-call" open>'
        f'<summary><span class="tool-name">{esc_name}</span>'
        f'<span class="tool-desc">{esc_desc}</span></summary>'
        f'<div class="tool-body"><pre><code class="language-json">{esc_inp}</code></pre></div>'
        f'</details>'
        + result_html
    )


def render_subagent_block(agent_id: str, invocation_input: dict, tool_result_content) -> str:
    """Render a subagent's full transcript inline, in place of the usual tool_use/result pair."""
    entries = _subagent_entries.get(agent_id, [])
    meta    = _subagent_meta.get(agent_id, {})

    subtype = invocation_input.get('subagent_type') or meta.get('agentType') or ''
    desc    = invocation_input.get('description')    or meta.get('description') or ''
    prompt  = invocation_input.get('prompt', '')

    cost, toks = subagent_session_stats(agent_id)

    # Build a tool_map local to this subagent so its own tool_use/tool_result pairs resolve.
    sub_tool_map = build_tool_map(entries)

    # Filter to visible user/assistant entries the same way convert() does.
    def is_real_user_local(e: dict) -> bool:
        if e.get('isMeta'):
            return False
        content = e.get('message', {}).get('content', '')
        if isinstance(content, str):
            if '<local-command-caveat>' in content:
                return False
            return bool(content.strip())
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict):
                    if b.get('type') == 'text' and b.get('text', '').strip():
                        return True
                    if b.get('type') == 'tool_result':
                        return True
        return False

    def is_real_asst_local(e: dict) -> bool:
        content = e.get('message', {}).get('content', [])
        if not isinstance(content, list):
            return False
        return any(isinstance(b, dict) and b.get('type') in ('text', 'tool_use') for b in content)

    visible: list[dict] = []
    for e in entries:
        t = e.get('type')
        if t == 'user' and is_real_user_local(e):
            visible.append(e)
        elif t == 'assistant' and is_real_asst_local(e):
            visible.append(e)

    # Per-turn / cumulative cost for token badges (local to the subagent)
    cost_by_uuid: dict[str, tuple[float, float]] = {}
    cumul = 0.0
    for e in entries:
        if e.get('type') != 'assistant':
            continue
        msg   = e.get('message', {})
        model = msg.get('model', '')
        if model == '<synthetic>':
            continue
        usage = msg.get('usage') or {}
        if not usage:
            continue
        try:
            tc = calc_cost(usage, model)
        except Exception:
            tc = 0.0
        cumul += tc
        cost_by_uuid[e.get('uuid', '')] = (tc, cumul)

    msg_parts: list[str] = []
    for idx, e in enumerate(visible):
        uid = e.get('uuid', '')
        tc, cc = cost_by_uuid.get(uid, (0.0, 0.0))
        html = render_message(e, sub_tool_map, turn_cost=tc, cumul_cost=cc,
                              msg_idx=idx, time_delta=None)
        if html:
            msg_parts.append(html)

    # Header: badge + description + running total
    summary_bits = []
    if subtype:
        summary_bits.append(f'<span class="sa-type">{_e(subtype)}</span>')
    if desc:
        summary_bits.append(f'<span class="sa-desc">{_e(desc)}</span>')
    summary_bits.append(f'<span class="sa-stats">{fmt_tok(toks)} · {fmt_cost(cost)}</span>')

    return (
        f'<details class="subagent-block" open>'
        f'<summary>'
        f'<span class="sa-badge">Subagent</span>'
        + ''.join(summary_bits)
        + f'</summary>'
        f'<div class="sa-body">'
        + ''.join(msg_parts)
        + f'</div>'
        f'</details>'
    )


def render_tool_result_inline(content, tool_name: str = '') -> str:
    # WebSearch: try structured card rendering first
    if tool_name == 'WebSearch':
        ws = _try_render_web_search(content)
        if ws:
            return ws

    has_images = False
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for cb in content:
            if isinstance(cb, dict):
                if cb.get('type') == 'text':
                    parts.append(cb.get('text', ''))
                elif cb.get('type') == 'image':
                    src = cb.get('source', {})
                    if src.get('type') == 'base64':
                        mt   = src.get('media_type', 'image/png')
                        data = src.get('data', '')
                        parts.append(f'<img class="inline-image" src="data:{mt};base64,{data}">')
                        has_images = True
            else:
                parts.append(str(cb))
        text = '\n'.join(parts)
    else:
        text = str(content)

    if has_images:
        # Don't re-escape already-rendered img tags; wrap with minimal escaping
        esc = text  # already contains safe <img> HTML
        preview = 'image result'
    else:
        esc     = _e(text)
        preview = ' '.join(esc.split('\n')[0].split())[:80]

    return (
        f'<details class="tool-result">'
        f'<summary>Result — {preview}</summary>'
        f'<div class="result-body">{esc}</div>'
        f'</details>'
    )


def render_token_badge(usage: dict, model: str, turn_cost: float, cumul_cost: float) -> str:
    """Compact inline pill: tokens breakdown + turn cost + cumulative."""
    inp   = usage.get('input_tokens', 0)
    cw    = usage.get('cache_creation_input_tokens', 0)
    cr    = usage.get('cache_read_input_tokens', 0)
    out   = usage.get('output_tokens', 0)
    color = cost_color(turn_cost)

    short_model = model.replace('claude-', '').replace('-20', '')[:16]

    parts = []
    if inp:   parts.append(f'<span class="tok-seg" title="input tokens">in:{fmt_tok(inp)}</span>')
    if cw:    parts.append(f'<span class="tok-seg" title="cache write tokens">cw:{fmt_tok(cw)}</span>')
    if cr:    parts.append(f'<span class="tok-seg" title="cache read tokens">cr:{fmt_tok(cr)}</span>')
    if out:   parts.append(f'<span class="tok-seg" title="output tokens">out:{fmt_tok(out)}</span>')

    sep  = '<span class="tok-sep"> | </span>'
    cost_html = (
        f'<span class="turn-cost" style="color:{color}" title="estimated cost this turn">'
        f'{fmt_cost(turn_cost)}</span>'
    )
    cumul_html = (
        f'<span class="cumul" title="cumulative session cost so far">'
        f'&#x2211;{fmt_cost(cumul_cost)}</span>'
    )
    model_html = f'<span class="tok-seg" style="color:var(--text-dimmer)">{short_model}</span>'

    inner = sep.join(parts + [cost_html, cumul_html, model_html])
    return f'<span class="token-badge" title="Token usage for this turn">{inner}</span>'


# ---------------------------------------------------------------------------
# Build tool_id -> result map
# ---------------------------------------------------------------------------

def build_tool_map(entries: list) -> dict:
    tool_map: dict[str, object] = {}
    for entry in entries:
        if entry.get('type') != 'user':
            continue
        content = entry.get('message', {}).get('content', [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                tid = block.get('tool_use_id', '')
                if tid:
                    tool_map[tid] = block.get('content', '')
    return tool_map


# ---------------------------------------------------------------------------
# Subagent support
#
# When Claude Code dispatches a subagent via the Agent tool, the subagent's
# conversation is logged in a sibling file:
#   projects/{proj}/{sessionId}/subagents/agent-{agentId}.jsonl
# with a {agentType, description} sidecar at .meta.json.
#
# The subagents folder is flat regardless of nesting depth — a sub-subagent
# spawned from a subagent lives in the same folder, not a nested one. The
# tool_use -> agentId correlation is: parent's tool_result entry has
# toolUseResult.agentId which matches the agent-{id}.jsonl filename.
#
# Module state is populated once per convert() call via load_subagent_context().
# ---------------------------------------------------------------------------

_subagent_entries: dict[str, list[dict]] = {}   # agentId -> entries
_subagent_meta:    dict[str, dict]       = {}   # agentId -> {agentType, description}
_agent_id_by_tool: dict[str, str]        = {}   # tool_use_id -> agentId (flat, all depths)


def build_agent_id_map(entries: list) -> dict:
    """tool_use_id -> agentId for every Agent tool call whose result has toolUseResult.agentId."""
    out: dict[str, str] = {}
    for e in entries:
        if e.get('type') != 'user':
            continue
        tur = e.get('toolUseResult')
        if not isinstance(tur, dict):
            continue
        aid = tur.get('agentId')
        if not aid:
            continue
        content = e.get('message', {}).get('content', [])
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get('type') == 'tool_result':
                    tid = b.get('tool_use_id', '')
                    if tid:
                        out[tid] = aid
                        break
    return out


def load_subagent_context(session_jsonl: Path) -> None:
    """Populate module-level subagent state by scanning the sibling subagents/ folder."""
    _subagent_entries.clear()
    _subagent_meta.clear()
    _agent_id_by_tool.clear()

    sa_dir = session_jsonl.parent / session_jsonl.stem / "subagents"
    if not sa_dir.is_dir():
        return

    for sa_file in sorted(sa_dir.glob("*.jsonl")):
        stem = sa_file.stem
        agent_id = stem[len("agent-"):] if stem.startswith("agent-") else stem
        entries: list[dict] = []
        try:
            with open(sa_file, encoding='utf-8', errors='replace') as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entries.append(json.loads(raw))
                    except Exception:
                        pass
        except Exception:
            continue
        _subagent_entries[agent_id] = entries

        meta_path = sa_file.parent / (stem + '.meta.json')
        if meta_path.exists():
            try:
                _subagent_meta[agent_id] = json.loads(meta_path.read_text(encoding='utf-8'))
            except Exception:
                pass

        # Index Agent tool_use -> agentId mappings found INSIDE this subagent too
        # (so recursive rendering resolves correctly).
        for tid, aid in build_agent_id_map(entries).items():
            _agent_id_by_tool[tid] = aid


def aggregate_subagent_usage(agg: dict, calc_cost_fn) -> tuple[float, set]:
    """Walk every loaded subagent and add its usage to agg. Return (added_cost, models_seen)."""
    added = 0.0
    models: set = set()
    for entries in _subagent_entries.values():
        for e in entries:
            if e.get('type') != 'assistant':
                continue
            msg = e.get('message', {})
            model = msg.get('model', '')
            if model == '<synthetic>':
                continue
            usage = msg.get('usage') or {}
            if not usage:
                continue
            if model:
                models.add(model)
            agg['input']       += usage.get('input_tokens', 0)
            agg['cache_write'] += usage.get('cache_creation_input_tokens', 0)
            agg['cache_read']  += usage.get('cache_read_input_tokens', 0)
            agg['output']      += usage.get('output_tokens', 0)
            agg['turns']       += 1
            try:
                added += calc_cost_fn(usage, model)
            except Exception:
                pass
    return added, models


def subagent_session_stats(agent_id: str) -> tuple[float, int]:
    """Return (cost, total_tokens) for a single subagent's own conversation."""
    entries = _subagent_entries.get(agent_id, [])
    cost = 0.0
    toks = 0
    for e in entries:
        if e.get('type') != 'assistant':
            continue
        msg = e.get('message', {})
        model = msg.get('model', '')
        if model == '<synthetic>':
            continue
        usage = msg.get('usage') or {}
        if not usage:
            continue
        try:
            cost += calc_cost(usage, model)
        except Exception:
            pass
        toks += (usage.get('input_tokens', 0)
                 + usage.get('cache_creation_input_tokens', 0)
                 + usage.get('cache_read_input_tokens', 0)
                 + usage.get('output_tokens', 0))
    return cost, toks


# ---------------------------------------------------------------------------
# Render a single message
# ---------------------------------------------------------------------------

def render_message(
    entry: dict,
    tool_map: dict,
    turn_cost: float = 0.0,
    cumul_cost: float = 0.0,
    msg_idx: int = 0,
    time_delta: float = None,
) -> str:
    role    = entry.get('type', '')
    ts      = entry.get('timestamp', '')
    msg     = entry.get('message', {})
    content = msg.get('content', '')
    usage   = msg.get('usage') if role == 'assistant' else None
    model   = msg.get('model', '')

    if role == 'user':
        role_class, badge = 'role-user', 'You'
    elif role == 'assistant':
        role_class, badge = 'role-asst', 'Claude'
    else:
        role_class, badge = 'role-system', role

    # Timestamp
    ts_str = ''
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            ts_str = dt.strftime('%H:%M:%S')
        except Exception:
            ts_str = ts[:19]

    # Token badge (assistant only, when usage present)
    badge_html = ''
    if usage and role == 'assistant':
        badge_html = render_token_badge(usage, model, turn_cost, cumul_cost)

    # Message anchor
    anchor_html = f'<a class="msg-anchor" href="#msg-{msg_idx}" title="permalink">¶</a>'

    meta_html = ''
    if ts_str or badge_html:
        meta_html = (
            f'<div class="msg-meta">'
            + (f'<span class="timestamp">{ts_str}</span>' if ts_str else '')
            + badge_html
            + anchor_html
            + '</div>'
        )

    # Tool ribbon — count tool calls for assistant turns
    tool_ribbon_html = ''
    if role == 'assistant' and isinstance(content, list):
        tool_counts: dict[str, int] = {}
        for b in content:
            if isinstance(b, dict) and b.get('type') == 'tool_use':
                n = b.get('name', 'unknown')
                tool_counts[n] = tool_counts.get(n, 0) + 1
        if tool_counts:
            chips = []
            for n, cnt in sorted(tool_counts.items(), key=lambda x: -x[1]):
                label = f'{n} ×{cnt}' if cnt > 1 else n
                chips.append(f'<span class="tool-chip">{_e(label)}</span>')
            tool_ribbon_html = f'<div class="tool-ribbon">{"".join(chips)}</div>'

    # Timing delta — "responded in Xs" shown at bottom of assistant messages
    timing_html = ''
    if time_delta is not None and role == 'assistant' and time_delta >= 1.0:
        secs = int(time_delta)
        if secs < 60:
            t_str = f'{secs}s'
        elif secs < 3600:
            t_str = f'{secs // 60}m {secs % 60}s'
        else:
            t_str = f'{secs // 3600}h {(secs % 3600) // 60}m'
        timing_html = f'<div class="timing-delta">⏱ responded in {t_str}</div>'

    # Content blocks
    blocks_html = ''
    if isinstance(content, str):
        if content.strip():
            blocks_html = render_text_block(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get('type', '')
            if btype == 'text':
                text = block.get('text', '')
                if text.strip():
                    blocks_html += render_text_block(text)
            elif btype == 'thinking':
                blocks_html += render_thinking_block(block.get('thinking', ''))
            elif btype == 'tool_use':
                blocks_html += render_tool_use_block(block, tool_map)
            elif btype == 'image':
                src = block.get('source', {})
                if src.get('type') == 'base64':
                    mt   = src.get('media_type', 'image/png')
                    data = src.get('data', '')
                    blocks_html += f'<img class="inline-image" src="data:{mt};base64,{data}">'

    if not blocks_html:
        return ''

    return (
        f'<div class="message {role_class}" id="msg-{msg_idx}">'
        f'  <div class="role-badge"><span>{badge}</span></div>'
        f'  <div class="message-body">'
        f'    {meta_html}'
        f'    {tool_ribbon_html}'
        f'    {blocks_html}'
        f'    {timing_html}'
        f'  </div>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Cost breakdown panel
# ---------------------------------------------------------------------------

def render_cost_panel(agg: dict, total_cost: float, models: set) -> str:
    inp   = agg.get('input', 0)
    cw    = agg.get('cache_write', 0)
    cr    = agg.get('cache_read', 0)
    out   = agg.get('output', 0)
    total_tok = inp + cw + cr + out

    # Default rates for cost breakdown (approximate — session may mix models)
    default_rates = _get_rates(next(iter(models), ''))
    inp_cost = inp * default_rates['input']       / 1_000_000
    cw_cost  = cw  * default_rates['cache_write'] / 1_000_000
    cr_cost  = cr  * default_rates['cache_read']  / 1_000_000
    out_cost = out * default_rates['output']       / 1_000_000

    models_str = ', '.join(sorted(m for m in models if m and m != '<synthetic>'))
    color = cost_color(total_cost / max(agg.get('turns', 1), 1))

    grid = f"""
    <div class="cost-grid">
      <div class="cost-cell">
        <div class="label">Input</div>
        <div class="value">{fmt_tok(inp)}</div>
        <div class="sub">{fmt_cost(inp_cost)}</div>
      </div>
      <div class="cost-cell">
        <div class="label">Cache Write</div>
        <div class="value">{fmt_tok(cw)}</div>
        <div class="sub">{fmt_cost(cw_cost)}</div>
      </div>
      <div class="cost-cell">
        <div class="label">Cache Read</div>
        <div class="value">{fmt_tok(cr)}</div>
        <div class="sub">{fmt_cost(cr_cost)}</div>
      </div>
      <div class="cost-cell">
        <div class="label">Output</div>
        <div class="value">{fmt_tok(out)}</div>
        <div class="sub">{fmt_cost(out_cost)}</div>
      </div>
    </div>
    <div class="cost-models">Models: <span>{models_str or 'unknown'}</span></div>
    <div class="cost-note">* Costs are estimates based on published API list prices. Actual billing may differ.</div>
    """

    return f"""
<div class="cost-panel">
  <details>
    <summary>
      <span class="cost-label">Session Cost Estimate</span>
      <span class="cost-total" style="color:{color}">{fmt_cost(total_cost)}</span>
      <span class="cost-label">&nbsp;|&nbsp; {fmt_tok(total_tok)} tokens total &nbsp;|&nbsp; {agg.get('turns', 0)} assistant turns</span>
    </summary>
    <div class="cost-body">{grid}</div>
  </details>
</div>"""


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert(jsonl_path: Path, out_path: Path) -> None:
    print(f"Reading {jsonl_path} ...")

    entries     = []
    session_id  = ''
    custom_title = ''

    with open(jsonl_path, encoding='utf-8', errors='replace') as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                entries.append(obj)
                if not session_id and obj.get('type') == 'permission-mode':
                    session_id = obj.get('sessionId', '')
                if obj.get('type') == 'custom-title':
                    custom_title = obj.get('title', '')
            except Exception:
                pass

    print(f"  {len(entries)} entries loaded")

    # Load any subagents spawned by this session (flat folder, includes descendants).
    load_subagent_context(jsonl_path)
    # Record parent's own Agent tool_use -> agentId mappings.
    for tid, aid in build_agent_id_map(entries).items():
        _agent_id_by_tool[tid] = aid

    tool_map = build_tool_map(entries)
    conv_entries = [e for e in entries if e.get('type') in ('user', 'assistant')]

    def is_real_user(e: dict) -> bool:
        if e.get('isMeta'):
            return False
        content = e.get('message', {}).get('content', '')
        if isinstance(content, str):
            if '<local-command-caveat>' in content:
                return False
            return bool(content.strip())
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    t = block.get('type', '')
                    if t == 'text' and block.get('text', '').strip():
                        return True
                    if t == 'tool_result':
                        return True
            return False
        return True

    def is_real_asst(e: dict) -> bool:
        content = e.get('message', {}).get('content', [])
        if not isinstance(content, list):
            return False
        return any(
            isinstance(b, dict) and b.get('type') in ('text', 'tool_use')
            for b in content
        )

    visible = []
    for e in conv_entries:
        if e.get('type') == 'user' and is_real_user(e):
            visible.append(e)
        elif e.get('type') == 'assistant' and is_real_asst(e):
            visible.append(e)

    print(f"  {len(visible)} visible messages")

    # ── Accumulate usage & compute per-turn costs ─────────────────────────────
    # Iterate ALL conv_entries (not just visible) so the total matches quick_scan().
    # Turns filtered by is_real_asst() (e.g. thinking-only, empty, interrupted) still
    # consume tokens and should be counted; their cost flows into the running cumul
    # seen by subsequent visible turns.
    agg = {'input': 0, 'cache_write': 0, 'cache_read': 0, 'output': 0, 'turns': 0}
    models_seen: set[str] = set()
    cumul = 0.0

    # Pre-compute (turn_cost, cumul_after) per entry uuid
    cost_by_uuid: dict[str, tuple[float, float]] = {}

    for e in conv_entries:
        if e.get('type') != 'assistant':
            continue
        msg   = e.get('message', {})
        model = msg.get('model', '')
        if model == '<synthetic>':
            continue
        usage = msg.get('usage', {})
        if not usage:
            continue

        if model:
            models_seen.add(model)
        agg['input']       += usage.get('input_tokens', 0)
        agg['cache_write'] += usage.get('cache_creation_input_tokens', 0)
        agg['cache_read']  += usage.get('cache_read_input_tokens', 0)
        agg['output']      += usage.get('output_tokens', 0)
        agg['turns']       += 1

        turn_cost = calc_cost(usage, model)
        cumul    += turn_cost
        cost_by_uuid[e.get('uuid', '')] = (turn_cost, cumul)

    # Roll in every subagent's own API usage (not reflected in parent's usage entries).
    sa_added, sa_models = aggregate_subagent_usage(agg, calc_cost)
    cumul      += sa_added
    models_seen |= sa_models

    total_cost = cumul
    total_tokens_all = agg['input'] + agg['cache_write'] + agg['cache_read'] + agg['output']

    # ── Timing deltas — time between consecutive messages ─────────────────────
    delta_by_uuid: dict[str, float] = {}
    prev_ts_str: str = ''
    for e in visible:
        ts = e.get('timestamp', '')
        if ts and prev_ts_str and e.get('type') == 'assistant':
            try:
                dt1 = datetime.fromisoformat(prev_ts_str.replace('Z', '+00:00'))
                dt2 = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                delta = (dt2 - dt1).total_seconds()
                if 0 < delta < 7200:  # ignore unreasonable deltas
                    delta_by_uuid[e.get('uuid', '')] = delta
            except Exception:
                pass
        if ts:
            prev_ts_str = ts

    # ── Render messages ────────────────────────────────────────────────────────
    msg_parts = []
    for idx, e in enumerate(visible):
        uid = e.get('uuid', '')
        tc, cc = cost_by_uuid.get(uid, (0.0, 0.0))
        td = delta_by_uuid.get(uid)
        html = render_message(e, tool_map, turn_cost=tc, cumul_cost=cc,
                              msg_idx=idx, time_delta=td)
        if html:
            msg_parts.append(html)

    messages_html = '\n'.join(msg_parts)

    # ── Stats ─────────────────────────────────────────────────────────────────
    user_turns = sum(1 for e in visible if e.get('type') == 'user')
    asst_turns = sum(1 for e in visible if e.get('type') == 'assistant')
    tool_calls = sum(
        sum(1 for b in e.get('message', {}).get('content', [])
            if isinstance(b, dict) and b.get('type') == 'tool_use')
        for e in visible if e.get('type') == 'assistant'
    )

    # Title / meta
    title = custom_title or jsonl_path.stem[:60]
    first_ts = last_ts = ''
    for e in conv_entries:
        ts = e.get('timestamp', '')
        if ts and not first_ts:
            first_ts = ts
        if ts:
            last_ts = ts
    try:
        d1 = datetime.fromisoformat(first_ts.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M')
        d2 = datetime.fromisoformat(last_ts.replace('Z', '+00:00')).strftime('%H:%M')
        meta = f'{d1} - {d2} UTC'
    except Exception:
        meta = ''

    # Session duration
    duration_str = '—'
    if first_ts and last_ts:
        try:
            dt1 = datetime.fromisoformat(first_ts.replace('Z', '+00:00'))
            dt2 = datetime.fromisoformat(last_ts.replace('Z', '+00:00'))
            secs = int((dt2 - dt1).total_seconds())
            if secs < 60:
                duration_str = f'{secs}s'
            elif secs < 3600:
                duration_str = f'{secs // 60}m {secs % 60}s'
            else:
                h = secs // 3600
                m = (secs % 3600) // 60
                duration_str = f'{h}h {m}m'
        except Exception:
            pass

    cost_panel_html = render_cost_panel(agg, total_cost, models_seen)

    html = HTML_TEMPLATE.format(
        title=title,
        meta=meta,
        cost_panel_html=cost_panel_html,
        messages_html=messages_html,
        msg_count=len(visible),
        user_turns=user_turns,
        asst_turns=asst_turns,
        tool_calls=tool_calls,
        total_tokens=fmt_tok(total_tokens_all),
        duration_str=duration_str,
        total_cost_str=fmt_cost(total_cost),
        session_id=session_id[:16] + '...' if len(session_id) > 16 else session_id,
    )

    out_path.write_text(html, encoding='utf-8')
    size_kb = out_path.stat().st_size // 1024
    print(f"  Written: {out_path}  ({size_kb} KB)")
    print(f"  Total tokens: {fmt_tok(total_tokens_all)}  |  Est. cost: {fmt_cost(total_cost)}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    jsonl_path = Path(sys.argv[1])
    if not jsonl_path.exists():
        sys.exit(f"ERROR: File not found: {jsonl_path}")

    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else jsonl_path.with_suffix('.html')
    convert(jsonl_path, out_path)
    print("Done.")


if __name__ == '__main__':
    main()
