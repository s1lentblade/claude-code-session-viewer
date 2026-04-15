#!/usr/bin/env python3
"""
Take 7 README screenshots.
Sources:
  - index.html (real data, obfuscated) — hero, split-panel, analytics-spend,
                                          analytics-hours, themes
  - example-index.html (fake data)     — analytics-heatmap
  - demo/macOS/archive/caad9c1b-...    — session-detail (direct open)
"""
import json, re, subprocess
from pathlib import Path
from PIL import Image

CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
ROOT   = Path('E:/claude-sessions-git')
SRC    = ROOT / 'index.html'
DEMO_INDEX = ROOT / 'example-index.html'
TMP    = ROOT / '_ss_readme_tmp.html'
ASSETS = ROOT / 'assets'

HIDE_SCROLL = (
    '<style>'
    '::-webkit-scrollbar{width:0!important;height:0!important}'
    'html,body{overflow:hidden!important;background:#000!important;min-height:100vh!important}'
    '</style>'
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_and_patch(src_path):
    """Load HTML, apply dark/blurple mode, redact personal identifiers."""
    text = src_path.read_text(encoding='utf-8')

    # Force dark mode + blurple theme
    text = (text
        .replace("let darkMode     = false;", "let darkMode     = true;")
        .replace("let darkMode = false;",     "let darkMode = true;")
        .replace("let currentTheme    = 'amber';", "let currentTheme    = 'blurple';")
        .replace("let currentTheme = 'amber';",    "let currentTheme = 'blurple';")
    )

    # Redact personal names and project identifiers
    text = (text
        .replace('Silent', 'alex')
        .replace('silent', 'alex')
        .replace('kurtislin', 'morgan')
        .replace('ABTI', 'Nexus')
        .replace('abti', 'nexus')
        .replace('youmind.com', 'example.com')
        .replace('PaperBrain', 'Scholarly')
    )

    # Truncate project paths in SESSIONS JSON to last 2 segments
    m = re.search(r'(const SESSIONS\s*=\s*)(\[.*?\]);', text, re.DOTALL)
    if m:
        sessions = json.loads(m.group(2))
        for s in sessions:
            proj = s.get('project', '')
            if proj:
                parts = [p.strip() for p in proj.replace('\\', '/').split('/') if p.strip()]
                s['project'] = ' / '.join(parts[-2:]) if len(parts) >= 2 else proj
        text = text[:m.start(2)] + json.dumps(sessions, separators=(',',':')) + text[m.end(2):]

    # Hide scrollbars
    text = text.replace('</head>', HIDE_SCROLL + '</head>', 1)
    return text


def shoot(name, html, w=1440, h=900):
    """Write TMP, shell out to Chrome, print result size."""
    TMP.write_text(html, encoding='utf-8')
    out = str(ASSETS / name)
    subprocess.run(
        [CHROME, '--headless=new', '--disable-gpu',
         f'--window-size={w},{h}', f'--screenshot={out}',
         '--virtual-time-budget=5000', TMP.as_uri()],
        capture_output=True, check=True
    )
    img = Image.open(out)
    print(f'  {name}: {img.size}')
    return img


def crop_save(name, box):
    """Crop an existing asset to box=(left, top, right, bottom) and overwrite."""
    path = str(ASSETS / name)
    img = Image.open(path)
    w, h = img.size
    l, t, r, b = box
    cropped = img.crop((l, t, min(r, w), min(b, h)))
    cropped.save(path)
    print(f'  {name} cropped -> {cropped.size}')
    return cropped

# ── Shot functions ────────────────────────────────────────────────────────────

def take_hero():
    print('hero.png...')
    text = load_and_patch(SRC)
    # Sort by cost descending; sessions are already group-rendered by project
    html = text + "<script>setSort('cost');</script>"
    shoot('hero.png', html, 1440, 900)


def take_split_panel():
    print('split-panel.png...')
    text = load_and_patch(SRC)
    demo_path = 'demo/macOS/archive/caad9c1b-a8a0-4dd3-96c1-12b01562d554.html'
    demo_title = 'I have a Python script that parses a 2GB CSV...'
    js = f"setSort('cost'); openViewer('{demo_path}', '{demo_title}');"
    html = text + f'<script>{js}</script>'
    shoot('split-panel.png', html, 1440, 900)


def take_session_detail():
    """Open the demo Python→Rust session directly and screenshot it."""
    print('session-detail.png...')
    session_html = ROOT / 'demo/macOS/archive/caad9c1b-a8a0-4dd3-96c1-12b01562d554.html'
    text = session_html.read_text(encoding='utf-8')
    text = text.replace('</head>', HIDE_SCROLL + '</head>', 1)
    # Expand the first <details> block (tool call) so it's visible
    expand_js = "document.querySelectorAll('details').forEach(d => d.open = true);"
    html = text + f'<script>{expand_js}</script>'
    shoot('session-detail.png', html, 1200, 800)


def take_analytics_spend():
    print('analytics-spend.png...')
    text = load_and_patch(SRC)
    js = "toggleTimeline(); setChartView('weekly');"
    html = text + f'<script>{js}</script>'
    shoot('analytics-spend.png', html, 1440, 1000)


def take_analytics_hours():
    print('analytics-hours.png...')
    text = load_and_patch(SRC)
    js = "toggleTimeline(); setChartView('hours');"
    html = text + f'<script>{js}</script>'
    shoot('analytics-hours.png', html, 1440, 1000)


def take_analytics_heatmap():
    """Spread example sessions across 52 weeks so the heatmap grid looks full."""
    import datetime, random
    print('analytics-heatmap.png...')
    text = load_and_patch(DEMO_INDEX)

    m = re.search(r'(const SESSIONS\s*=\s*)(\[.*?\]);', text, re.DOTALL)
    if m:
        sessions = json.loads(m.group(2))
        random.seed(42)
        today = datetime.date.today()
        # ~3-5 active days per week across 52 weeks gives a nicely full grid
        active_dates = []
        for week in range(52):
            base = today - datetime.timedelta(weeks=51 - week)
            n_days = random.randint(2, 5)
            day_offsets = sorted(random.sample(range(7), min(n_days, 7)))
            for off in day_offsets:
                d = base + datetime.timedelta(days=off)
                if d <= today:
                    active_dates.append(d)

        extended = []
        for i, date in enumerate(active_dates):
            s = dict(sessions[i % len(sessions)])
            ts = date.strftime('%Y-%m-%d') + ' 14:30'
            s['start_ts'] = ts
            s['date_sort'] = date.isoformat() + 'T14:30:00+00:00'
            s['session_id'] = f'heatmap-demo-{i:04d}'
            extended.append(s)

        text = text[:m.start(2)] + json.dumps(extended, separators=(',',':')) + text[m.end(2):]

    js = "toggleTimeline(); setChartView('heatmap');"
    html = text + f'<script>{js}</script>'
    shoot('analytics-heatmap.png', html, 1440, 1000)
    # Crop to just the grid + legend — insight cards show "0 active days" because
    # the synthetic dates don't feed into the insight calculation, so hide them.
    crop_save('analytics-heatmap.png', (0, 0, 1440, 310))


def take_themes():
    print('themes.png...')
    text = load_and_patch(SRC)
    js = "toggleThemePicker();"
    html = text + f'<script>{js}</script>'
    shoot('themes.png', html, 1440, 900)
    # Crop to top-right corner: show the swatch grid + session list context behind it
    # Picker grid sits at approx x=1040..1360, y=42..195 in the 1440-wide screenshot
    crop_save('themes.png', (920, 0, 1440, 210))


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    take_hero()
    take_split_panel()
    take_session_detail()
    take_analytics_spend()
    take_analytics_hours()
    take_analytics_heatmap()
    take_themes()
    TMP.unlink(missing_ok=True)
    print('Done.')
