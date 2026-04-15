# Generate Narrative Analytics Insights

Analyze this Claude session archive and produce rich, narrative insights for every analytics tab. Output is written to `insights-narrative.json` in the project root. Running `python scripts/merge_archives.py` then embeds these insights directly into `index.html`.

When no `insights-narrative.json` exists, the analytics panel falls back to computed stats automatically.

---

## Step 1 — Gather session data

Run the following to get a quick statistical summary you can reason from:

```bash
python -c "
import json, os, glob, collections
from datetime import datetime, timezone

sessions = []
for root, dirs, files in os.walk('.'):
    for f in files:
        if f.endswith('.jsonl') and 'RAWEVERYTHING' not in root:
            pass  # skip raw
for d in ['macOS', 'Windows', 'Claude.ai']:
    meta = os.path.join(d, 'archive', 'sessions_meta.json')
    if os.path.exists(meta):
        sessions += json.load(open(meta, encoding='utf-8'))

print(f'{len(sessions)} sessions loaded')
total = sum(s.get('cost',0) for s in sessions)
print(f'Total spend: \${total:.2f}')
models = collections.Counter(s.get('model','?') for s in sessions)
print('Models:', dict(models.most_common(5)))
dates = sorted(s['date_sort'][:10] for s in sessions if s.get('date_sort'))
if dates: print(f'Range: {dates[0]} to {dates[-1]}')
"
```

Also read `index.html` briefly — the `const SESSIONS = [...]` block contains all session metadata you need. The fields are:
- `cost` — estimated USD cost
- `model` — model slug (contains 'opus', 'sonnet', 'haiku')
- `ts` — Unix timestamp
- `date_sort` — ISO date string
- `project` — project path
- `total_tok` — total tokens
- `model_tokens` — per-model token breakdown `{model: {input, cache_write, cache_read, output}}`
- `model_costs` — per-model cost breakdown
- `platform_key` — 'macOS', 'Windows', 'Claude.ai', etc.
- `tool_counts` — dict of `{tool_name: call_count}` for every tool used in the session. MCP tools appear as `mcp__servername__toolname`.

---

## Step 2 — Compute key statistics for each view

For each of the 8 analytics views, compute these numbers from the session data:

| View | Key stats to compute |
|------|---------------------|
| `weekly` | avg $/week across active weeks, peak week (date + amount), last-4 vs prior-4 trend %, cost per paid session |
| `cumul` | total spend, days since first session, daily burn rate, projected 30-day and yearly cost, sessions/week cadence |
| `days` | sessions per day-of-week (0=Sun), peak day, weekday vs weekend %, avg cost on peak day, costliest day-of-week |
| `hours` | sessions per hour (0–23), peak hour, morning/afternoon/evening/night splits, after-hours (6pm+) % |
| `projects` | cost per project (top by spend), top project % of total, top-3 share %, project count, top vs bottom ratio |
| `models` | sessions per model family (opus/sonnet/haiku), % on top model, avg cost per session per family, Opus % of total spend |
| `heatmap` | active days in last 365, active day %, longest consecutive streak, busiest calendar month, avg spend on active days |
| `tokens` | total tokens (all types), cache hit rate (cache_read / (input + cache_read)), estimated cache savings, output/input ratio |
| `activity` | Classify each session by dominant `tool_counts` key: **coding** (Edit/Write > 0), **exploration** (Read/Glob/Grep, no edits), **automation** (Bash, no edits), **research** (WebSearch/WebFetch), **agent** (Agent tool), **mcp** (any `mcp__*` tool), **conversation** (no tools). Compute sessions + total cost per category, sorted by session count. Top category, coding %, tool-using session %, most expensive category. |
| `mcp` | From `tool_counts`, sum all `mcp__*` keys by server (second segment of `mcp__server__tool`). Total MCP calls, distinct server count, top server name + call count + % share, sessions that used any MCP tool. If no MCP usage, note that explicitly. |

---

## Step 3 — Write `insights-narrative.json`

Create the file at the project root with this structure. Each view has exactly 3–4 blocks. Each block needs:
- `value` — a short, punchy metric (number, name, or percentage)  
- `label` — 2–4 word lowercase label  
- `detail` — **2–3 full sentences** that interpret the data, not just restate it. Include specific numbers. Tell the user what the pattern *means*, not just what it *is*.

```json
{
  "generated": "<ISO timestamp>",
  "views": {
    "weekly": [
      {
        "value": "$14.20",
        "label": "avg per active week",
        "detail": "Your 18 spending weeks average $14.20 each. The last 4 weeks are up 23% vs the prior 4 — a meaningful climb worth watching if it continues."
      },
      {
        "value": "$38.40",
        "label": "peak week",
        "detail": "Week of Mar 10–16 was your biggest — 12 sessions totalling $38.40, nearly 3× your average. A classic sign of a deadline sprint or heavy project push."
      },
      {
        "value": "$2.10",
        "label": "cost per paid session",
        "detail": "142 of 208 sessions (68%) carried real API cost, averaging $2.10 each. At that level you're having substantial, context-heavy conversations — not quick one-liners."
      },
      {
        "value": "+23%",
        "label": "8-week spend trend",
        "detail": "Recent 4-week total: $56.80. Prior 4-week total: $46.20. A 23% uptick suggests a project ramp or deeper usage pattern taking hold — review if the trend continues into next month."
      }
    ],
    "cumul": [ ... ],
    "days": [ ... ],
    "hours": [ ... ],
    "projects": [ ... ],
    "models": [ ... ],
    "heatmap": [ ... ],
    "tokens": [ ... ],
    "activity": [
      {
        "value": "coding",
        "label": "most common activity",
        "detail": "..."
      },
      { "value": "22%", "label": "coding sessions", "detail": "..." },
      { "value": "79%", "label": "tool-using sessions", "detail": "..." },
      { "value": "agent", "label": "most expensive activity", "detail": "..." }
    ],
    "mcp": [
      { "value": "1,240", "label": "total MCP calls", "detail": "..." },
      { "value": "filesystem", "label": "top MCP server", "detail": "..." },
      { "value": "4", "label": "distinct MCP servers", "detail": "..." },
      { "value": "18%", "label": "sessions with MCP usage", "detail": "..." }
    ]
  }
}
```

**Tone guidelines:**
- Write in second person ("you", "your")
- Be direct — no filler phrases like "it's worth noting that" or "this is impressive"
- Praise where the data is genuinely good; flag a problem where it clearly exists; don't manufacture either to balance the other
- Compare numbers to each other to give context (e.g. "3× your average")
- Keep each `detail` under 60 words

---

## Step 4 — Write the `"analysis"` deep-dive section

The Analytics overlay has a dedicated **Summary** tab (last tab in the row) that renders a full narrative report with per-section mini-charts and inline data callouts. Populate it by adding an `"analysis"` key at the root of `insights-narrative.json`:

```json
{
  "views": { ... },
  "analysis": {
    "headline": "One-sentence characterization of the user's Claude relationship",
    "generated": "YYYY-MM-DD",
    "sections": [
      {
        "title": "Short italic-friendly section title (8 words max)",
        "body": "3–4 sentences. Cite specific numbers. Interpret patterns, don't just restate them. Write in second person ('you', 'your'). HTML is allowed for <strong>emphasis</strong>.",
        "metrics": [
          { "value": "$XX", "label": "short label" },
          { "value": "N%",  "label": "short label" },
          { "value": "Nx",  "label": "short label" }
        ]
      }
    ]
  }
}
```

**Write exactly 7–9 sections covering these topics (in this order):**

| # | Topic | What to include |
|---|-------|-----------------|
| 1 | Adoption arc | Speed of habit formation, streaks, first-session-to-daily cadence |
| 2 | Where money goes | Cost breakdown by project/platform; which projects dominate and why |
| 3 | When they work best | Peak hours, day-of-week patterns, what those patterns reveal about workflow |
| 4 | What they're building | Project taxonomy; which are infrastructure vs. experiments vs. daily ops |
| 5 | How they work | Activity breakdown — what % is coding vs. exploration vs. automation vs. conversation; what the mix reveals about workflow style |
| 6 | MCP tool usage | Which MCP servers are used, call volumes, what they indicate about the user's toolchain. If no MCP usage, note it and why that might be. |
| 7 | Model strategy | Sonnet/Opus/Haiku distribution; whether it's well-calibrated; missed opportunities |
| 8 | Token efficiency | Cache hit rate, output/input ratio; explain why these are good or bad |
| 9 | One thing to change | **Single most impactful structural recommendation** — specific and actionable |

**Tone principle**: Assess each section honestly. Praise where the data is genuinely good — don't soften a real strength with qualifications. Flag a problem where it clearly exists — name it, give the specific fix, move on. Don't manufacture criticism to balance praise, and don't pad praise to soften criticism. Not every section needs both. The goal is a useful, direct read.

**Quality bar for each section:**
- `body`: 3–4 sentences. Every sentence either cites a number or draws a concrete conclusion. No generic advice.
- `metrics`: Exactly 2–3 data points. Pick the most diagnostic numbers for that section.
- `title`: Descriptive is fine; evocative is better. "Cache performance is genuinely excellent" beats "Token Efficiency".

---

## Step 5 — Rebuild and verify

```bash
python scripts/merge_archives.py
```

Open `index.html` in a browser, click the Analytics button, and verify:

1. Each chart tab (Spend, Cumulative, etc.) shows narrative tiles and a summary paragraph instead of generic computed stats.
2. The **Summary** tab (last in the row) renders a scrollable report with section titles, body paragraphs, per-section mini-charts, and metric callouts.
3. If any tab shows generic stats, check that the view key in `insights-narrative.json` matches exactly (lowercase: `weekly`, `cumul`, `days`, `hours`, `projects`, `models`, `heatmap`, `tokens`, `activity`, `mcp`).
4. If Summary shows "No analysis generated yet", check that the `"analysis"` key exists at the root of `insights-narrative.json` (not nested inside `"views"`).

To revert to computed stats, delete `insights-narrative.json` and rebuild.
