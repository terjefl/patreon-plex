"""Track whether you have liked each downloaded post on Patreon.

Patreon rejects likes sent without the web app's CSRF token, so liking stays manual.
This only reads `current_user_has_liked`, so the index page can list the episodes you
have watched in Plex but not liked yet.
"""

import json
import logging
import os
import random
import threading
import time
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request

from . import plex
from .config import Config, CreatorConfig
from .harvest import Harvester
from .state import State

log = logging.getLogger(__name__)

# Besides watched-but-not-liked posts (always checked), refresh this many other posts per run.
BACKGROUND_CHECKS_PER_RUN = 20
RECHECK_AFTER_DAYS = 7
PAUSE_BETWEEN_CHECKS = (1.0, 4.0)

_lock = threading.Lock()


class LikeStore:
    """data/<creator>/likes.json: {post_id: {"liked": bool, "checked": epoch, "marked_watched": epoch}}"""

    def __init__(self, cfg: Config, creator: CreatorConfig):
        self.path = cfg.data_dir / creator.creator / "likes.json"

    def load(self) -> dict[str, dict]:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}

    def update(self, post_id: str, liked: bool | None = None, **extra) -> None:
        with _lock:
            data = self.load()
            entry = data.setdefault(post_id, {})
            if liked is not None:
                entry.update(liked=liked, checked=int(time.time()))
            entry.update(extra)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1))
            os.replace(tmp, self.path)


def post_files(state_posts: dict[str, dict]) -> dict[Path, str]:
    """Library file path -> post id, for downloaded posts."""
    return {Path(f): pid for pid, p in state_posts.items() if p.get("status") == "done" for f in p.get("files", [])}


def has_liked(ydl: YoutubeDL, post_id: str) -> bool:
    url = f"https://www.patreon.com/api/posts/{post_id}?fields[post]=current_user_has_liked&json-api-version=1.0"
    data = json.loads(ydl.urlopen(Request(url)).read())
    return bool(data["data"]["attributes"].get("current_user_has_liked"))


def check_likes(cfg: Config, creator: CreatorConfig, only_watched: bool = False, all_posts: bool = False) -> int:
    """Refresh like status: all watched-but-not-liked posts, plus a few stale/unknown ones."""
    h = Harvester(cfg, creator, dry_run=True)
    h.refresh_cookies()
    store = LikeStore(cfg, creator)
    known = store.load()
    by_file = post_files(h.state.posts)
    watched = {by_file[e.path] for e in plex.episodes(cfg, cfg.section_for(creator)) if e.watched and e.path in by_file}

    urgent = [pid for pid in watched if not known.get(pid, {}).get("liked")]
    stale_before = time.time() - RECHECK_AFTER_DAYS * 86400
    background = []
    if not only_watched:
        others = [pid for pid in set(by_file.values()) - set(urgent) if known.get(pid, {}).get("checked", 0) < stale_before]
        others.sort(key=lambda pid: known.get(pid, {}).get("checked", 0))
        background = others if all_posts else others[:BACKGROUND_CHECKS_PER_RUN]

    checked = 0
    with YoutubeDL(h._params()) as ydl:
        for i, pid in enumerate(urgent + background):
            if i:
                time.sleep(random.uniform(*PAUSE_BETWEEN_CHECKS))
            try:
                store.update(pid, has_liked(ydl, pid))
                checked += 1
            except Exception as e:
                log.warning("Could not check like status for %s: %s", pid, e)
    if checked:
        log.info("%s: checked like status for %d post(s)", h.creator_name, checked)
    return checked


def mark_liked_watched(cfg: Config, creator: CreatorConfig) -> int:
    """Mark episodes as watched in Plex when you have liked the post on Patreon.

    A like means you have seen it (often before it was downloaded). Each episode is marked
    at most once, so setting one back to unwatched in Plex sticks.
    """
    by_file = post_files(State(cfg.data_dir / creator.creator / "state.json").posts)
    store = LikeStore(cfg, creator)
    known = store.load()
    marked = 0
    for ep in plex.episodes(cfg, cfg.section_for(creator)):
        pid = by_file.get(ep.path)
        if not pid or ep.watched:
            continue
        info = known.get(pid, {})
        if info.get("liked") and not info.get("marked_watched"):
            plex.mark_watched(cfg, ep.rating_key)
            store.update(pid, marked_watched=int(time.time()))
            log.info("Marked as watched in Plex (liked on Patreon): %s %s", ep.show, ep.title)
            marked += 1
    return marked
