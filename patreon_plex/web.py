"""Index page: every downloaded episode, with links, Plex watched status and Patreon likes,
plus the posts that are missing, in the place they would have had."""

import html
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import plex
from .config import Config, CreatorConfig
from .harvest import MAX_ATTEMPTS, Harvester
from .likes import LikeStore, check_likes, post_files
from .state import State

log = logging.getLogger(__name__)

CACHE_SECONDS = 60


@dataclass
class Row:
    creator: str
    show: str
    season: int
    episode: int
    title: str
    aired: str
    watched: bool
    liked: bool | None  # None = not checked yet
    patreon_url: str
    plex_url: str
    rating_key: str
    missing: str | None = None  # why a post has no episode: shown instead of watched/liked
    missing_detail: str = ""

    @property
    def code(self) -> str:
        if not self.episode:
            return f"S{self.season:02d}" if self.season < 1000 else str(self.season)
        return f"S{self.season:02d}E{self.episode:02d}" if self.season < 1000 else f"{self.season} #{self.episode}"


class Index:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._cache: tuple[float, list[Row]] | None = None
        self._refreshing = threading.Lock()

    def rows(self) -> list[Row]:
        if self._cache and time.time() - self._cache[0] < CACHE_SECONDS:
            return self._cache[1]
        episodes = plex.episodes(self.cfg)
        rows: list[Row] = []
        for creator in self.cfg.creators:
            state = State(self.cfg.data_dir / creator.creator / "state.json")
            by_file = post_files(state.posts)
            likes = LikeStore(self.cfg, creator).load()
            name = creator.creator_name or creator.creator
            for ep in episodes:
                post_id = by_file.get(ep.path)
                if not post_id:
                    continue
                rows.append(
                    Row(
                        creator=name,
                        show=ep.show,
                        season=ep.season,
                        episode=ep.episode,
                        title=ep.title,
                        aired=ep.aired,
                        watched=ep.watched,
                        liked=likes[post_id]["liked"] if post_id in likes else None,
                        patreon_url=f"https://www.patreon.com/posts/{post_id}",
                        plex_url=plex.web_link(self.cfg, ep.rating_key),
                        rating_key=ep.rating_key,
                    )
                )
            rows.extend(_missing_rows(self.cfg, creator, state))
        self._cache = (time.time(), rows)
        return rows

    def refresh_likes(self) -> bool:
        """Re-check likes for watched posts in the background. False if already running."""
        if not self._refreshing.acquire(blocking=False):
            return False

        def work():
            try:
                for creator in self.cfg.creators:
                    check_likes(self.cfg, creator, only_watched=True)
            except Exception:
                log.exception("Like refresh failed")
            finally:
                self._cache = None
                self._refreshing.release()

        threading.Thread(target=work, daemon=True).start()
        return True

    def set_watched(self, keys: list[str], watched: bool) -> int:
        """Mark episodes (Plex rating keys) as watched/unwatched; only keys listed on the page."""
        allowed = {r.rating_key for r in self.rows()}
        keys = [k for k in keys if k in allowed]
        for key in keys:
            (plex.mark_watched if watched else plex.mark_unwatched)(self.cfg, key)
        self._cache = None
        return len(keys)

    @property
    def refreshing(self) -> bool:
        return self._refreshing.locked()


def _missing_rows(cfg: Config, creator: CreatorConfig, state: State) -> list[Row]:
    """Posts that should have been an episode but aren't (yet), placed as the harvester would."""
    planner = Harvester(cfg, creator, dry_run=True)
    rows = []
    for post_id, post in list(state.posts.items()):
        status = post.get("status")
        if status not in ("failed", "no_access", "pending") or "published" not in post:
            continue
        if creator.since and datetime.fromtimestamp(post["published"], tz=UTC).date() < creator.since:
            continue
        if status == "failed":
            attempts = post.get("attempts", 0)
            reason = "Gitt opp" if attempts >= MAX_ATTEMPTS else f"Feilet ({attempts}/{MAX_ATTEMPTS})"
        else:
            reason = "Ingen tilgang" if status == "no_access" else "I kø"
        numbered = "number" in post
        ep = planner.plan({"id": post_id, "title": post.get("title"), "timestamp": post["published"]})
        # The planner hands out the next free number to unnumbered posts; that guess isn't theirs yet.
        episode = ep.episode if numbered or "number" not in planner.state.posts[post_id] else 0
        rows.append(
            Row(
                creator=creator.creator_name or creator.creator,
                show=ep.show_title,
                season=ep.season,
                episode=episode,
                title=ep.title or post.get("title") or post_id,
                aired=ep.published.date().isoformat(),
                watched=False,
                liked=None,
                patreon_url=f"https://www.patreon.com/posts/{post_id}",
                plex_url="",
                rating_key="",
                missing=reason,
                missing_detail=_short_error(post.get("error", "")),
            )
        )
    return rows


def _short_error(error: str) -> str:
    """'ERROR: [dailymotion] k1z...: Not found.' -> 'dailymotion: Not found.'"""
    m = re.search(r"\[(\w+)\] [^:]+: (.*?)(?: \(caused by .*)?$", error.strip())
    return f"{m.group(1)}: {m.group(2)}" if m else error.strip()[:200]


def _e(text) -> str:
    return html.escape(str(text))


def _badge(value: bool | None, yes: str, no: str) -> str:
    if value is None:
        return '<span class="b unk" title="Ikke sjekket ennå">?</span>'
    label, short, cls = (yes, "✓", "yes") if value else (no, "✗", "no")
    return f'<span class="b {cls}" title="{label}"><span class="long">{label}</span><span class="short">{short}</span></span>'


def _watched_button(r: Row) -> str:
    label, short, cls = ("Sett", "✓", "yes") if r.watched else ("Ikke sett", "✗", "no")
    return (
        f'<button class="b {cls} wbtn" data-key="{_e(r.rating_key)}" data-watched="{int(r.watched)}" '
        f'title="Klikk for å merke som {"ikke sett" if r.watched else "sett"} i Plex">'
        f'<span class="long">{label}</span><span class="short">{short}</span></button>'
    )


def _row_html(r: Row, show_name: bool = False) -> str:
    if r.missing:
        return _missing_row_html(r, show_name)
    cls = " ".join(c for c, on in (("unwatched", not r.watched), ("unliked", r.liked is not True)) if on)
    show = f'<span class="show">{_e(r.show)}</span> ' if show_name else ""
    return (
        f'<tr class="{cls}" data-key="{_e(r.rating_key)}"><td class="code">{_e(r.code)}</td>'
        f"<td>{show}{_e(r.title)}</td>"
        f'<td class="date">{_e(r.aired)}</td>'
        f"<td>{_watched_button(r)}</td>"
        f"<td>{_badge(r.liked, 'Likt', 'Ikke likt')}</td>"
        f'<td class="links"><a href="{_e(r.patreon_url)}" target="_blank" rel="noopener">Patreon</a>'
        f'<a href="{_e(r.plex_url)}" target="_blank" rel="noopener">Plex</a></td></tr>'
    )


def _missing_row_html(r: Row, show_name: bool = False) -> str:
    show = f'<span class="show">{_e(r.show)}</span> ' if show_name else ""
    cls = "queued" if r.missing == "I kø" else "gone"
    return (
        f'<tr class="missing"><td class="code">{_e(r.code)}</td>'
        f"<td>{show}{_e(r.title)}</td>"
        f'<td class="date">{_e(r.aired)}</td>'
        f'<td colspan="2"><span class="b {cls}" title="{_e(r.missing_detail)}">{_e(r.missing)}</span>'
        f'<span class="why">{_e(r.missing_detail)}</span></td>'
        f'<td class="links"><a href="{_e(r.patreon_url)}" target="_blank" rel="noopener">Patreon</a></td></tr>'
    )


def render(index: Index) -> str:
    all_rows = index.rows()
    rows = [r for r in all_rows if not r.missing]
    missing = [r for r in all_rows if r.missing]
    todo = sorted((r for r in rows if r.watched and r.liked is not True), key=lambda r: r.aired)
    shows: dict[tuple[str, str], list[Row]] = {}
    for r in all_rows:
        shows.setdefault((r.creator, r.show), []).append(r)
    # Creator's own "misc" show last, the rest alphabetically
    order = sorted(shows, key=lambda k: (k[1] == k[0], k[1].casefold()))

    head = "<thead><tr><th>Ep.</th><th>Tittel</th><th>Dato</th><th>Sett</th><th>Likt</th><th></th></tr></thead>"
    parts = []
    if todo:
        body = "".join(_row_html(r, show_name=True) for r in todo)
        parts.append(
            f'<section class="todo"><h2>Sett, men ikke likt <span class="n">{len(todo)}</span></h2>'
            f"<table>{head}<tbody>{body}</tbody></table></section>"
        )
    else:
        parts.append('<section class="todo done"><h2>Alt du har sett er likt 👍</h2></section>')
    for key in order:
        both = sorted(shows[key], key=lambda r: (r.season == 0, r.season, r.episode or 10**6, r.aired))
        eps = [r for r in both if not r.missing]
        gone = len(both) - len(eps)
        seen = sum(r.watched for r in eps)
        body = "".join(_row_html(r) for r in both)
        unseen = [r.rating_key for r in eps if not r.watched]
        all_btn = (
            f'<button class="allbtn" data-keys="{_e(",".join(unseen))}">Merk alle som sett</button>' if unseen else ""
        )
        parts.append(
            f"<details open><summary><h2>{_e(key[1])}</h2>"
            f'<span class="meta">{all_btn}{len(eps)} ep · {seen} sett{f" · {gone} mangler" if gone else ""}</span>'
            "</summary>"
            f"<table>{head}<tbody>{body}</tbody></table></details>"
        )

    watched = sum(r.watched for r in rows)
    liked = sum(r.liked is True for r in rows)
    refresh = (
        '<button disabled>Sjekker likerklikk …</button>'
        if index.refreshing
        else '<form method="post" action="refresh"><button>Sjekk likerklikk nå</button></form>'
    )
    return PAGE.format(
        summary=f"{len(rows)} episoder · {watched} sett · {liked} likt"
        + (f" · {len(missing)} mangler" if missing else ""),
        refresh=refresh,
        content="".join(parts),
        updated=time.strftime("%d.%m.%Y %H:%M"),
    )


PAGE = """<!doctype html>
<html lang="no"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Patreon-videoer</title>
<style>
:root {{ --bg:#f6f5f2; --fg:#1d1d1f; --muted:#6b6b70; --card:#fff; --line:#e4e2dd; --accent:#e5622b;
  --yes:#1f7a3f; --yes-bg:#e3f3e8; --no:#8a5a00; --no-bg:#fbefd5; --unk:#6b6b70; --unk-bg:#ecebe8;
  --gone:#a3262a; --gone-bg:#fbe3e2; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141416; --fg:#ececee; --muted:#9a9aa1; --card:#1e1e21;
  --line:#2e2e33; --accent:#ff7a45; --yes:#6fd393; --yes-bg:#1d3326; --no:#f2c46b; --no-bg:#3a2f17;
  --unk:#9a9aa1; --unk-bg:#2a2a2e; --gone:#ff8a80; --gone-bg:#3d1f1f; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 -apple-system,system-ui,Segoe UI,Roboto,sans-serif }}
main {{ max-width:1000px; margin:0 auto; padding:24px 16px 64px }}
header {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; margin-bottom:20px }}
h1 {{ margin:0; font-size:24px }} .sub {{ color:var(--muted) }}
h2 {{ display:inline; font-size:17px; margin:0 }}
.filters {{ display:flex; gap:6px; flex-wrap:wrap }}
button, .filters label {{ font:inherit; border:1px solid var(--line); background:var(--card); color:var(--fg);
  border-radius:999px; padding:6px 12px; cursor:pointer }}
.filters input {{ display:none }} .filters input:checked + span {{ color:var(--accent); font-weight:600 }}
section, details {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; margin:12px 0 }}
.todo {{ border-color:var(--accent) }} .todo.done {{ border-color:var(--line) }}
.n {{ background:var(--accent); color:#fff; border-radius:999px; padding:1px 8px; font-size:13px; margin-left:6px }}
summary {{ cursor:pointer; list-style:none; display:flex; justify-content:space-between; align-items:baseline; gap:8px }}
summary::-webkit-details-marker {{ display:none }}
.meta {{ color:var(--muted); font-size:13px; white-space:nowrap }}
table {{ width:100%; border-collapse:collapse; margin-top:8px; table-layout:fixed }}
th:nth-child(1) {{ width:84px }} th:nth-child(3) {{ width:104px }} th:nth-child(4) {{ width:84px }}
th:nth-child(5) {{ width:92px }} th:nth-child(6) {{ width:120px }}
td:nth-child(2) {{ overflow-wrap:anywhere }}
th {{ text-align:left; color:var(--muted); font-weight:500; font-size:12px; text-transform:uppercase; letter-spacing:.04em }}
th, td {{ padding:6px 8px; border-top:1px solid var(--line); vertical-align:middle }}
.code, .date {{ white-space:nowrap; font-variant-numeric:tabular-nums; color:var(--muted) }}
.show {{ color:var(--muted) }}
.b {{ display:inline-block; font-size:12px; border-radius:6px; padding:1px 7px; white-space:nowrap }}
.yes {{ color:var(--yes); background:var(--yes-bg) }} .no {{ color:var(--no); background:var(--no-bg) }}
.unk {{ color:var(--unk); background:var(--unk-bg) }} .short {{ display:none }}
button.b {{ border:0; font:inherit; font-size:12px; cursor:pointer }} button.b:hover {{ outline:1px solid currentColor }}
button.b[disabled], .allbtn[disabled] {{ opacity:.5; cursor:wait }}
.allbtn {{ font-size:12px; padding:2px 10px; margin-right:10px }}
.links {{ white-space:nowrap; text-align:right }} .links a {{ color:var(--accent); margin-left:10px; text-decoration:none }}
.links a:hover {{ text-decoration:underline }}
body.f-unwatched tbody tr:not(.unwatched), body.f-unliked tbody tr:not(.unliked),
  body.f-missing tbody tr:not(.missing), body.f-missing details:not(:has(tr.missing)),
  body.f-missing section.todo {{ display:none }}
tr.missing td {{ color:var(--muted) }} tr.missing td:nth-child(2) {{ font-style:italic }}
.gone {{ color:var(--gone); background:var(--gone-bg) }} .queued {{ color:var(--unk); background:var(--unk-bg) }}
.why {{ font-size:12px; color:var(--muted); margin-left:8px }}
footer {{ color:var(--muted); font-size:13px; margin-top:24px }}
@media (max-width:640px) {{ .date, th:nth-child(3) {{ display:none }} th, td {{ padding:6px 4px }}
  th:nth-child(1) {{ width:62px }} th:nth-child(4), th:nth-child(5) {{ width:40px }} th:nth-child(6) {{ width:60px }}
  .long {{ display:none }} .short {{ display:inline }}
  .links a {{ display:block; margin:2px 0 }} .why {{ display:none }} }}
</style></head>
<body><main>
<header><div><h1>Patreon-videoer</h1><div class="sub">{summary}</div></div>
<div class="filters">
<label><input type="radio" name="f" value="" checked><span>Alle</span></label>
<label><input type="radio" name="f" value="f-unwatched"><span>Ikke sett</span></label>
<label><input type="radio" name="f" value="f-unliked"><span>Ikke likt</span></label>
<label><input type="radio" name="f" value="f-missing"><span>Mangler</span></label>
{refresh}</div></header>
{content}
<footer>Oppdatert {updated}. «Sett» kommer fra Plex. Likerklikk sjekkes hver time (sette episoder først), eller med knappen over. Poster som mangler står i kursiv der episoden skulle vært; hold over merket for å se feilen.</footer>
</main>
<script>
document.querySelectorAll('.filters input').forEach(i => i.addEventListener('change', () => {{
  document.body.className = i.value; try {{ localStorage.setItem('f', i.value) }} catch (e) {{}}
}}));
async function setWatched(keys, watched) {{
  const r = await fetch('watched', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ keys, watched }}) }});
  if (!r.ok) throw new Error(await r.text());
}}
function paint(key, watched) {{
  document.querySelectorAll(`.wbtn[data-key="${{key}}"]`).forEach(b => {{
    b.dataset.watched = watched ? '1' : '0';
    b.classList.toggle('yes', watched); b.classList.toggle('no', !watched);
    b.querySelector('.long').textContent = watched ? 'Sett' : 'Ikke sett';
    b.querySelector('.short').textContent = watched ? '✓' : '✗';
    b.closest('tr').classList.toggle('unwatched', !watched);
  }});
}}
document.addEventListener('click', async e => {{
  const b = e.target.closest('.wbtn, .allbtn');
  if (!b) return;
  e.preventDefault(); e.stopPropagation();
  b.disabled = true;
  try {{
    if (b.classList.contains('wbtn')) {{
      const watched = b.dataset.watched !== '1';
      await setWatched([b.dataset.key], watched); paint(b.dataset.key, watched);
    }} else {{
      await setWatched(b.dataset.keys.split(','), true); location.reload(); return;
    }}
  }} catch (err) {{ alert('Klarte ikke å oppdatere Plex: ' + err.message); }}
  b.disabled = false;
}});
try {{ const f = localStorage.getItem('f'); if (f) {{ const i = document.querySelector(`.filters input[value="${{f}}"]`);
  if (i) {{ i.checked = true; document.body.className = f }} }} }} catch (e) {{}}
</script>
</body></html>
"""


def serve(cfg: Config, port: int) -> ThreadingHTTPServer:
    index = Index(cfg)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: str = "", ctype: str = "text/html; charset=utf-8", headers=()):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                try:
                    self._send(200, render(index))
                except Exception as e:
                    log.exception("Rendering index failed")
                    self._send(500, f"<p>Kunne ikke lage siden: {_e(e)}</p>")
            elif self.path == "/health":
                self._send(200, "ok", "text/plain")
            else:
                self._send(404, "Not found", "text/plain")

        def do_POST(self):
            if self.path == "/refresh":
                index.refresh_likes()
                self._send(303, headers=[("Location", "./")])
            elif self.path == "/watched":
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                    n = index.set_watched([str(k) for k in body.get("keys", [])], bool(body.get("watched")))
                    self._send(200, json.dumps({"updated": n}), "application/json")
                except Exception as e:
                    log.exception("Updating watched status failed")
                    self._send(500, str(e), "text/plain")
            else:
                self._send(404, "Not found", "text/plain")

        def log_message(self, fmt, *args):
            log.debug("web: " + fmt, *args)

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Index page on port %d", port)
    return server
