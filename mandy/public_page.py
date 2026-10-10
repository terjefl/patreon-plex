"""Public list of everything Mandy has posted, on Patreon and YouTube, linking to each.

In English, for sharing, and free of anything private: no watched or liked status, no Plex links,
nothing about downloads. Patreon posts that aren't downloaded (yet) are listed like the rest, since
the page is about what she made, not what is on the server; YouTube is the whole channel.
"""

import html
import json
import re
import time

from .config import Config, CreatorConfig
from .stats import load_youtube

YOUTUBE_KINDS = {"video": "YouTube", "live": "YouTube livestreams", "short": "YouTube Shorts"}


def _e(text) -> str:
    return html.escape(str(text))


def items(rows: list, cfg: Config, creator: CreatorConfig) -> list[dict]:
    """One entry per Patreon post (parts of a post merged) and per YouTube video on the channel."""
    posts: dict[str, dict] = {}
    for r in rows:
        if r.source != "patreon":
            continue
        entry = posts.get(r.patreon_url)
        if entry:
            entry["d"] += r.duration
            continue
        title = re.sub(r"\s+-\s+pt\d+$", "", r.title)
        show = r.show.removeprefix(r.creator + " - ") if r.show != r.creator else r.show
        posts[r.patreon_url] = {
            "s": "patreon", "show": show, "code": r.code, "t": title, "date": r.aired,
            "d": r.duration, "url": r.patreon_url,
        }
    out = list(posts.values())
    youtube = load_youtube(cfg, creator)
    for vid in youtube["listed"]:
        video = youtube["videos"].get(vid, {})
        if video.get("members_only"):
            continue  # members only: no date and no public page to link to
        kind = video.get("kind", "video")
        out.append({
            "s": "youtube", "show": YOUTUBE_KINDS.get(kind, "YouTube"), "code": "", "t": video.get("title", ""),
            "date": video.get("date", ""), "d": float(video.get("duration") or 0),
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    return out


def render_videos(rows: list, cfg: Config, creator: CreatorConfig) -> str:
    entries = items(rows, cfg, creator)
    # The JSON sits in a <script> element; "</" must not end it early
    data = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return PAGE.format(name=_e(creator.creator_name or creator.creator), data=data, updated=time.strftime("%-d %b %Y"))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}: all videos</title>
<style>
:root {{ color-scheme: light; --bg:#f6f5f2; --card:#fcfcfb; --fg:#0b0b0b; --muted:#52514e; --line:#e4e2dd;
  --accent:#c4471a; --patreon:#2a78d6; --video:#eb6834; }}
@media (prefers-color-scheme: dark) {{ :root {{ color-scheme: dark; --bg:#121211; --card:#1a1a19; --fg:#fff;
  --muted:#c3c2b7; --line:#2e2e2b; --accent:#ff7a45; --patreon:#3987e5; --video:#d95926; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,system-ui,Segoe UI,Roboto,sans-serif }}
main {{ max-width:1000px; margin:0 auto; padding:28px 16px 64px }}
h1 {{ margin:0; font-size:28px }} h2 {{ display:inline; font-size:17px; margin:0 }}
.sub {{ color:var(--muted) }} .sub a {{ color:var(--accent) }}
.controls {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:18px 0 10px }}
.controls label {{ border:1px solid var(--line); background:var(--card); border-radius:999px; padding:6px 12px; cursor:pointer }}
.controls input[type=radio] {{ display:none }} .controls input:checked + span {{ color:var(--accent); font-weight:600 }}
.sep {{ width:1px; align-self:stretch; background:var(--line); margin:0 4px }}
input[type=search] {{ font:inherit; flex:1 1 220px; min-width:0; padding:7px 12px; border:1px solid var(--line);
  border-radius:999px; background:var(--card); color:var(--fg) }}
.count {{ color:var(--muted); font-size:13px; margin:0 0 6px }}
details {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:10px 14px; margin:10px 0 }}
summary {{ cursor:pointer; list-style:none; display:flex; justify-content:space-between; align-items:baseline; gap:8px }}
summary::-webkit-details-marker {{ display:none }} .meta {{ color:var(--muted); font-size:13px; white-space:nowrap }}
table {{ width:100%; border-collapse:collapse; margin-top:6px; table-layout:fixed }}
td {{ padding:6px 8px; border-top:1px solid var(--line); vertical-align:middle }}
td.code {{ width:76px }} td.date {{ width:104px }} td.dur {{ width:72px; text-align:right }} td.link {{ width:96px; text-align:right }}
td.title {{ overflow-wrap:anywhere }} .code, .date, .dur {{ color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap }}
.show {{ color:var(--muted) }}
.link a {{ text-decoration:none; font-size:13px; border-radius:6px; padding:2px 8px; white-space:nowrap; color:#fff }}
.link a.patreon {{ background:var(--patreon) }} .link a.youtube {{ background:var(--video) }}
.link a:hover {{ filter:brightness(1.1) }}
footer {{ color:var(--muted); font-size:13px; margin-top:24px }}
@media (max-width:640px) {{ td.date, td.dur {{ display:none }} td {{ padding:6px 4px }} td.code {{ width:56px }} td.link {{ width:80px }} }}
</style></head>
<body><main>
<h1>{name}</h1>
<div class="sub">All videos, on Patreon and YouTube · <a href="statistikk">In numbers</a></div>
<div class="controls">
<label><input type="radio" name="view" value="shows" checked><span>By show</span></label>
<label><input type="radio" name="view" value="new"><span>Newest first</span></label>
<span class="sep"></span>
<label><input type="radio" name="src" value="" checked><span>All</span></label>
<label><input type="radio" name="src" value="patreon"><span>Patreon</span></label>
<label><input type="radio" name="src" value="youtube"><span>YouTube</span></label>
<input type="search" placeholder="Search titles and shows" aria-label="Search">
</div>
<p class="count"></p>
<div id="list"></div>
<footer>Updated {updated}. Patreon lists her video posts (a video posted in parts counts once); YouTube is
everything on the channel, members-only videos excepted. Links go straight to Patreon and YouTube.</footer>
</main>
<script type="application/json" id="data">{data}</script>
<script>
const all = JSON.parse(document.getElementById('data').textContent);
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const list = document.getElementById('list'), count = document.querySelector('.count');
const q = document.querySelector('input[type=search]');
function dur(s) {{ const m = Math.round(s / 60); return !m ? '' : m >= 60 ? `${{Math.floor(m / 60)}} h ${{String(m % 60).padStart(2, '0')}} m` : `${{m}} m`; }}
function plural(n) {{ return `${{n.toLocaleString('en')}} video${{n === 1 ? '' : 's'}}`; }}
// Newest first, undated last
function byDate(a, b) {{ return (!a.date) - (!b.date) || b.date.localeCompare(a.date); }}
function el(tag, cls, text) {{ const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }}
function row(it, withShow) {{
  const tr = el('tr');
  tr.append(el('td', 'code', it.code));
  const t = el('td', 'title');
  if (withShow) {{ t.append(el('span', 'show', it.show + ' ')); }}
  t.append(document.createTextNode(it.t));
  tr.append(t, el('td', 'date', it.date), el('td', 'dur', dur(it.d)));
  const l = el('td', 'link'), a = el('a', it.s, it.s === 'patreon' ? 'Patreon' : 'YouTube');
  a.href = it.url; a.target = '_blank'; a.rel = 'noopener'; l.append(a); tr.append(l);
  return tr;
}}
function group(title, items, withShow) {{
  const d = el('details'); d.open = true;
  const s = el('summary'); s.append(el('h2', null, title), el('span', 'meta', `${{plural(items.length)}} · ${{dur(items.reduce((n, i) => n + i.d, 0)) || '0 m'}}`));
  const table = el('table'), body = el('tbody');
  items.forEach(it => body.append(row(it, withShow)));
  table.append(body); d.append(s, table); return d;
}}
function render() {{
  const view = document.querySelector('input[name=view]:checked').value;
  const src = document.querySelector('input[name=src]:checked').value;
  const words = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
  const shown = all.filter(it => (!src || it.s === src) && words.every(w => (it.t + ' ' + it.show).toLowerCase().includes(w)));
  count.textContent = `${{plural(shown.length)}} · ${{dur(shown.reduce((n, i) => n + i.d, 0)) || '0 m'}}`;
  const groups = new Map();
  if (view === 'shows') {{
    // Patreon shows in episode order; YouTube newest first
    const sorted = [...shown].sort((a, b) => a.s === 'youtube' && b.s === 'youtube' ? byDate(a, b)
      : a.code.localeCompare(b.code, 'en', {{ numeric: true }}) || a.date.localeCompare(b.date));
    sorted.forEach(it => {{ if (!groups.has(it.show)) groups.set(it.show, []); groups.get(it.show).push(it); }});
    const own = k => /^(Mandy Cane Lane|YouTube)/.test(k);
    const keys = [...groups.keys()].sort((a, b) => own(a) - own(b) || a.localeCompare(b));
    list.replaceChildren(...keys.map(k => group(k, groups.get(k), false)));
  }} else {{
    const sorted = [...shown].sort(byDate);
    sorted.forEach(it => {{
      const k = it.date ? `${{MONTHS[+it.date.slice(5, 7) - 1]}} ${{it.date.slice(0, 4)}}` : 'Date not known yet';
      if (!groups.has(k)) groups.set(k, []); groups.get(k).push(it);
    }});
    list.replaceChildren(...[...groups].map(([k, v]) => group(k, v, true)));
  }}
}}
document.querySelectorAll('.controls input[type=radio]').forEach(i => i.addEventListener('change', render));
let timer; q.addEventListener('input', () => {{ clearTimeout(timer); timer = setTimeout(render, 150); }});
render();
</script>
</body></html>
"""
