"""Public statistics page: how much video a creator has made, on Patreon and on YouTube.

In English, for sharing with the creator, and free of anything private: no watched or liked
status, no Plex links, nothing about downloads.
"""

import html
import json
import time

from .config import Config, CreatorConfig
from .stats import aggregate, collect

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
LABELS = {"patreon": "Patreon", "video": "YouTube videos", "live": "YouTube livestreams", "short": "YouTube Shorts"}


def _e(text) -> str:
    return html.escape(str(text))


def hours(seconds: float) -> str:
    """'171 h 44 m'; under an hour '44 m'."""
    m = round(seconds / 60)
    return f"{m // 60:,} h {m % 60:02d} m" if m >= 60 else f"{m} m"


def _tile(value: str, label: str, note: str, key: str = "") -> str:
    swatch = f'<span class="key k-{key}"></span>' if key else ""
    return f'<div class="tile"><div class="label">{swatch}{_e(label)}</div><div class="big">{_e(value)}</div><div class="note">{_e(note)}</div></div>'


def _chart(months: dict, first: str) -> str:
    """Hours per month, Patreon and YouTube videos side by side, from `first` (YYYY-MM)."""
    keys = []
    y, m = int(first[:4]), int(first[5:7])
    last = max(months)
    while f"{y}-{m:02d}" <= last:
        keys.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    series = ("patreon", "video")
    values = {k: [months.get(k, {}).get(s, [0, 0])[1] / 3600 for s in series] for k in keys}
    top = max([max(v) for v in values.values()] + [1])
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50, 100) if top / s <= 5)
    ymax = step * (int(top // step) + 1)
    w, h, left, bottom, top_pad = 960, 280, 40, 24, 8
    plot_w, plot_h = w - left - 8, h - bottom - top_pad
    band = plot_w / len(keys)
    bar = max(2.0, min(12.0, (band - 4) / 2))
    parts = []
    for t in range(0, ymax + 1, step):
        yy = top_pad + plot_h - plot_h * t / ymax
        parts.append(f'<line class="grid" x1="{left}" x2="{w - 8}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="tick" x="{left - 6}" y="{yy + 4:.1f}" text-anchor="end">{t}</text>')
    for i, k in enumerate(keys):
        x0 = left + i * band + (band - (2 * bar + 2)) / 2
        for j, (s, v) in enumerate(zip(series, values[k])):
            if v <= 0:
                continue
            bh = plot_h * v / ymax
            x, yy = x0 + j * (bar + 2), top_pad + plot_h - bh
            r = min(4, bar / 2, bh)
            # rounded data end, square at the baseline
            parts.append(
                f'<path class="bar s-{s}" d="M{x:.1f},{top_pad + plot_h:.1f} V{yy + r:.1f} Q{x:.1f},{yy:.1f} {x + r:.1f},{yy:.1f} '
                f'H{x + bar - r:.1f} Q{x + bar:.1f},{yy:.1f} {x + bar:.1f},{yy + r:.1f} V{top_pad + plot_h:.1f} Z"/>'
            )
        # a year label at each January, and at the start unless a January follows closely
        if k.endswith("-01") or (i == 0 and int(k[5:7]) <= 9):
            parts.append(f'<text class="tick" x="{left + i * band + band / 2:.1f}" y="{h - 6}" text-anchor="middle">{k[:4]}</text>')
        parts.append(
            f'<rect class="hit" x="{left + i * band:.1f}" y="{top_pad}" width="{band:.1f}" height="{plot_h}" '
            f'data-m="{k}" data-p="{values[k][0]:.2f}" data-v="{values[k][1]:.2f}" tabindex="0"/>'
        )
    parts.append(f'<line class="axis" x1="{left}" x2="{w - 8}" y1="{top_pad + plot_h}" y2="{top_pad + plot_h}"/>')
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Hours of video per month, Patreon and YouTube videos">'
        + "".join(parts)
        + "</svg>"
    )


def _year_table(years: dict, total: dict) -> str:
    present = [k for k in ("patreon", "video", "live", "short") if total[k][0]]
    head = "".join(f'<th colspan="2">{_e(LABELS[k])}</th>' for k in present)
    sub = "".join("<th>Videos</th><th>Hours</th>" for _ in present)

    def row(label, data, cls=""):
        cells = "".join(
            f"<td>{data[k][0] or ''}</td><td>{hours(data[k][1]) if data[k][0] else ''}</td>" for k in present
        )
        return f'<tr class="{cls}"><th scope="row">{_e(label)}</th>{cells}</tr>'

    body = "".join(row(y, d) for y, d in years.items()) + row("Total", total, "total")
    return f'<table class="years"><thead><tr><th rowspan="2">Year</th>{head}</tr><tr>{sub}</tr></thead><tbody>{body}</tbody></table>'


def _month_table(months: dict, kind: str) -> str:
    years = sorted({k[:4] for k, v in months.items() if v[kind][0]})
    if not years:
        return ""
    head = "".join(f"<th>{m}</th>" for m in MONTHS)
    rows = []
    for y in years:
        cells = "".join(
            f"<td>{hours(months[k][kind][1]) if (k := f'{y}-{i:02d}') in months and months[k][kind][0] else ''}</td>"
            for i in range(1, 13)
        )
        total = sum(v[kind][1] for k, v in months.items() if k.startswith(y))
        rows.append(f'<tr><th scope="row">{y}</th>{cells}<td class="sum">{hours(total)}</td></tr>')
    return (
        f'<h3>{_e(LABELS[kind])}, hours per month</h3><div class="scroll"><table class="months">'
        f"<thead><tr><th>Year</th>{head}<th>Year total</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_stats(cfg: Config, creator: CreatorConfig) -> str:
    data = aggregate(collect(cfg, creator))
    name = creator.creator_name or creator.creator
    total, months = data["total"], data["months"]
    patreon_months = [k for k, v in months.items() if v["patreon"][0]]
    since = patreon_months[0] if patreon_months else min(months, default="")
    since_label = f"{MONTHS[int(since[5:7]) - 1]} {since[:4]}" if since else ""
    all_seconds = sum(v[1] for v in total.values())

    tiles = []
    if total["patreon"][0]:
        tiles.append(_tile(hours(total["patreon"][1]), "Patreon", f"{total['patreon'][0]:,} videos since {since_label}", "patreon"))
    if total["video"][0]:
        tiles.append(_tile(hours(total["video"][1]), "YouTube videos", f"{total['video'][0]:,} videos", "video"))
    if total["live"][0]:
        tiles.append(_tile(hours(total["live"][1]), "YouTube livestreams", f"{total['live'][0]:,} streams"))
    tiles.append(_tile(hours(all_seconds), "Altogether", f"about {round(all_seconds / 86400):,} days of video, back to back"))

    chart = ""
    if since:
        chart = (
            '<section><h2>Hours per month</h2>'
            '<div class="legend"><span><span class="key k-patreon"></span>Patreon</span>'
            '<span><span class="key k-video"></span>YouTube videos</span></div>'
            f'<div class="chart">{_chart(months, since)}<div class="tip" hidden></div></div>'
            f'<p class="note">Since {since_label}, when the Patreon started. Earlier YouTube years are in the table below.</p></section>'
        )
    month_tables = "".join(_month_table(months, k) for k in ("patreon", "video"))
    return PAGE.format(
        name=_e(name),
        tiles="".join(tiles),
        chart=chart,
        years=_year_table(data["years"], total),
        months=month_tables,
        updated=time.strftime("%-d %b %Y"),
        series=json.dumps([LABELS["patreon"], LABELS["video"]]),
    )


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} in numbers</title>
<style>
:root {{ color-scheme: light; --bg:#f6f5f2; --card:#fcfcfb; --fg:#0b0b0b; --muted:#52514e; --line:#e4e2dd;
  --grid:#ecebe7; --patreon:#2a78d6; --video:#eb6834; }}
@media (prefers-color-scheme: dark) {{ :root {{ color-scheme: dark; --bg:#121211; --card:#1a1a19; --fg:#fff;
  --muted:#c3c2b7; --line:#2e2e2b; --grid:#262624; --patreon:#3987e5; --video:#d95926; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,system-ui,Segoe UI,Roboto,sans-serif }}
main {{ max-width:1000px; margin:0 auto; padding:28px 16px 64px }}
h1 {{ margin:0; font-size:28px }} h2 {{ font-size:18px; margin:0 0 10px }} h3 {{ font-size:15px; margin:18px 0 6px }}
.sub, .note {{ color:var(--muted) }} .note {{ font-size:13px; margin:6px 0 0 }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:20px 0 }}
.tile, section {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px }}
section {{ margin:12px 0 }}
.tile .label {{ color:var(--muted); font-size:13px; display:flex; align-items:center; gap:6px }}
.tile .big {{ font-size:26px; font-weight:650; font-variant-numeric:tabular-nums; margin:2px 0 }}
.key {{ display:inline-block; width:10px; height:10px; border-radius:3px }} .k-patreon {{ background:var(--patreon) }}
.k-video {{ background:var(--video) }}
.legend {{ display:flex; gap:16px; font-size:13px; color:var(--muted); margin-bottom:6px }}
.legend > span {{ display:flex; align-items:center; gap:6px }}
.chart {{ position:relative }} svg {{ width:100%; height:auto; display:block }}
.grid {{ stroke:var(--grid); stroke-width:1 }} .axis {{ stroke:var(--line); stroke-width:1 }}
.tick {{ fill:var(--muted); font-size:11px }} .bar.s-patreon {{ fill:var(--patreon) }} .bar.s-video {{ fill:var(--video) }}
.hit {{ fill:transparent; outline:none }} .hit:hover, .hit:focus {{ fill:var(--grid); fill-opacity:.5 }}
.tip {{ position:absolute; pointer-events:none; background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:6px 10px; font-size:13px; box-shadow:0 4px 14px rgba(0,0,0,.12); white-space:nowrap }}
.tip b {{ font-variant-numeric:tabular-nums }} .tip .row {{ display:flex; align-items:center; gap:6px }}
.tip .line {{ width:12px; height:2px; display:inline-block }}
table {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums }}
th, td {{ padding:5px 8px; border-top:1px solid var(--line); text-align:right; white-space:nowrap }}
th:first-child {{ text-align:left }} thead th {{ color:var(--muted); font-weight:500; font-size:12px; border-top:0 }}
.years thead th {{ text-align:center }} .years thead tr:first-child th:first-child {{ text-align:left; vertical-align:bottom }}
tr.total td, tr.total th {{ font-weight:650; border-top:2px solid var(--line) }}
.months td {{ font-size:13px }} .months .sum {{ font-weight:600 }}
.scroll {{ overflow-x:auto }}
footer {{ color:var(--muted); font-size:13px; margin-top:24px }}
@media (max-width:640px) {{ .years {{ font-size:13px }} th, td {{ padding:4px 5px }} }}
</style></head>
<body><main>
<h1>{name}</h1>
<div class="sub">Hours of video, on Patreon and YouTube</div>
<div class="tiles">{tiles}</div>
{chart}
<section><h2>Year by year</h2><div class="scroll">{years}</div></section>
<section><h2>Month by month</h2>{months}</section>
<footer>Updated {updated}. Patreon counts the videos in her posts; a video posted in parts counts once.
YouTube counts what is on the channel today: videos, livestreams and Shorts.</footer>
</main>
<script>
const names = {series};
const tip = document.querySelector('.tip');
function fmt(h) {{ const m = Math.round(h * 60); return m >= 60 ? `${{Math.floor(m / 60)}} h ${{String(m % 60).padStart(2, '0')}} m` : `${{m}} m`; }}
function show(e) {{
  const r = e.target, box = r.closest('.chart').getBoundingClientRect(), rb = r.getBoundingClientRect();
  const [y, m] = r.dataset.m.split('-');
  tip.replaceChildren();
  const title = document.createElement('div'); title.textContent = new Date(y, m - 1).toLocaleString('en', {{ month: 'long', year: 'numeric' }});
  tip.append(title);
  [['p', 'patreon'], ['v', 'video']].forEach(([k, s], i) => {{
    const row = document.createElement('div'); row.className = 'row';
    const line = document.createElement('span'); line.className = 'line'; line.style.background = `var(--${{s}})`;
    const b = document.createElement('b'); b.textContent = fmt(+r.dataset[k]);
    row.append(line, b, document.createTextNode(' ' + names[i])); tip.append(row);
  }});
  tip.hidden = false;
  const x = Math.min(Math.max(rb.left - box.left + rb.width / 2 - tip.offsetWidth / 2, 0), box.width - tip.offsetWidth);
  tip.style.left = x + 'px'; tip.style.top = (rb.top - box.top - tip.offsetHeight + 8) + 'px';
}}
document.querySelectorAll('.hit').forEach(r => {{
  r.addEventListener('pointerenter', show); r.addEventListener('focus', show);
  r.addEventListener('pointerleave', () => tip.hidden = true); r.addEventListener('blur', () => tip.hidden = true);
}});
</script>
</body></html>
"""
