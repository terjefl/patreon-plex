"""How much video a creator has made: Patreon from the library, YouTube from the channel.

The YouTube channel's lists give each video's length but not its date, so dates come from one
request per video. Those are remembered in data/<creator>/youtube.json, and a refresh only asks
about videos it hasn't seen.
"""

import json
import logging
import os
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from . import plex
from .config import Config, CreatorConfig
from .state import State

log = logging.getLogger(__name__)

# Channel tab -> kind of video
YOUTUBE_TABS = {"videos": "video", "streams": "live", "shorts": "short"}
KINDS = ("patreon", "video", "live", "short")
YOUTUBE_REFRESH_SECONDS = 20 * 3600
PAUSE_BETWEEN_VIDEOS = 1.0


class _Quiet:
    def debug(self, msg):
        log.debug(msg)

    info = debug

    def warning(self, msg):
        log.debug(msg)

    def error(self, msg):
        log.debug(msg)


def _catalog_path(cfg: Config, creator: CreatorConfig) -> Path:
    return cfg.data_dir / creator.creator / "youtube.json"


def load_youtube(cfg: Config, creator: CreatorConfig) -> dict:
    """{"checked": epoch, "listed": [ids on the channel], "videos": {id: {kind, date, duration, title}}}"""
    try:
        return json.loads(_catalog_path(cfg, creator).read_text())
    except FileNotFoundError:
        return {"checked": 0, "listed": [], "videos": {}}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def youtube_due(cfg: Config, creator: CreatorConfig) -> bool:
    return bool(creator.youtube_url) and time.time() - load_youtube(cfg, creator)["checked"] > YOUTUBE_REFRESH_SECONDS


def refresh_youtube(cfg: Config, creator: CreatorConfig, max_new: int | None = 300) -> int:
    """List the channel and look up the dates of videos not seen before (at most max_new per call,
    so a first run spreads over a few days). Returns how many videos still lack a date."""
    if not creator.youtube_url:
        return 0
    path = _catalog_path(cfg, creator)
    data = load_youtube(cfg, creator)
    base = creator.youtube_url.rstrip("/")
    listed: dict[str, tuple[str, float | None, str]] = {}
    tabs_ok = 0
    with YoutubeDL({"quiet": True, "extract_flat": "in_playlist", "logger": _Quiet()}) as ydl:
        for tab, kind in YOUTUBE_TABS.items():
            try:
                info = ydl.extract_info(f"{base}/{tab}", download=False)
            except DownloadError as e:
                log.info("YouTube %s/%s: %s", base, tab, e)  # a channel without streams has no such tab
                continue
            tabs_ok += 1
            for entry in info.get("entries") or []:
                if entry.get("id"):
                    listed.setdefault(entry["id"], (kind, entry.get("duration"), entry.get("title") or ""))
    if not tabs_ok:
        log.warning("Could not list %s; keeping the last YouTube list", base)
        return len([i for i in data["listed"] if i not in data["videos"]])

    videos = data["videos"]
    new = [vid for vid in listed if vid not in videos]
    todo = new if max_new is None else new[:max_new]
    with YoutubeDL({"quiet": True, "logger": _Quiet()}) as ydl:
        for n, vid in enumerate(todo, start=1):
            kind, duration, title = listed[vid]
            try:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False, process=False)
            except DownloadError as e:
                log.info("YouTube %s: %s", vid, e)
                continue
            day = info.get("upload_date") or ""
            videos[vid] = {
                "kind": kind,
                "date": f"{day[:4]}-{day[4:6]}-{day[6:8]}" if len(day) == 8 else "",
                "duration": info.get("duration") or duration or 0,
                "title": info.get("title") or title,
            }
            if n % 25 == 0:
                _save(path, data)
            time.sleep(PAUSE_BETWEEN_VIDEOS)
    data["listed"] = sorted(listed)
    data["checked"] = time.time()
    _save(path, data)
    left = len(new) - len(todo)
    log.info("%s: %d YouTube videos listed, %d looked up, %d left for later", creator.creator, len(listed), len(todo), left)
    return left


def collect(cfg: Config, creator: CreatorConfig) -> list[tuple[str, str, float]]:
    """(kind, YYYY-MM-DD, seconds) for every Patreon post in the library and every listed
    YouTube video with a known date. A Patreon post in parts counts once, with all its parts."""
    items: list[tuple[str, str, float]] = []
    if cfg.plex:
        seconds = {ep.path: ep.duration for ep in plex.episodes(cfg, cfg.section_for(creator))}
        for post in State(cfg.data_dir / creator.creator / "state.json").posts.values():
            if post.get("status") != "done" or "published" not in post:
                continue
            total = sum(seconds.get(Path(f), 0) for f in post.get("files", []))
            if total:
                day = datetime.fromtimestamp(post["published"], tz=UTC).strftime("%Y-%m-%d")
                items.append(("patreon", day, total))
    youtube = load_youtube(cfg, creator)
    for vid in youtube["listed"]:
        video = youtube["videos"].get(vid)
        if video and video["date"]:
            items.append((video["kind"], video["date"], float(video["duration"] or 0)))
    return items


def aggregate(items: list[tuple[str, str, float]]) -> dict:
    """{"months": {YYYY-MM: {kind: [count, seconds]}}, "years": {...}, "total": {kind: [count, seconds]}}"""
    months: dict[str, dict] = defaultdict(lambda: {k: [0, 0.0] for k in KINDS})
    years: dict[str, dict] = defaultdict(lambda: {k: [0, 0.0] for k in KINDS})
    total = {k: [0, 0.0] for k in KINDS}
    for kind, day, secs in items:
        for bucket in (months[day[:7]][kind], years[day[:4]][kind], total[kind]):
            bucket[0] += 1
            bucket[1] += secs
    return {"months": dict(sorted(months.items())), "years": dict(sorted(years.items())), "total": total}
