"""Like a Patreon post once you have watched its episode in Plex.

The download never plays the video through Patreon's player, so the creator sees no
sign of you watching. A like, sent only after Plex reports the episode as watched, is
a real signal without faking playback.
"""

import json
import logging
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError

from .config import Config

log = logging.getLogger(__name__)

MAX_LIKES_PER_RUN = 10
PAUSE_BETWEEN_LIKES = (5, 30)


class LikeRejected(Exception):
    """Patreon refused the like request itself (not a per-post problem); stop trying."""


def watched_files(cfg: Config) -> set[Path]:
    """Library paths (as this container sees them) of episodes Plex marks as watched."""
    plex = cfg.plex
    query = urllib.parse.urlencode({"X-Plex-Token": plex.token})
    req = urllib.request.Request(
        f"{plex.url.rstrip('/')}/library/sections/{plex.section_id}/allLeaves?{query}",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        items = json.loads(resp.read())["MediaContainer"].get("Metadata", [])
    plex_root = plex.library_path.rstrip("/")
    files: set[Path] = set()
    for item in items:
        if not item.get("viewCount"):
            continue
        for media in item.get("Media", []):
            for part in media.get("Part", []):
                path = part.get("file", "")
                if path.startswith(plex_root + "/"):
                    files.add(cfg.library_dir / path[len(plex_root) + 1 :])
    return files


def _has_liked(ydl: YoutubeDL, post_id: str) -> bool:
    url = f"https://www.patreon.com/api/posts/{post_id}?fields[post]=current_user_has_liked&json-api-version=1.0"
    data = json.loads(ydl.urlopen(Request(url)).read())
    return bool(data["data"]["attributes"].get("current_user_has_liked"))


def like(ydl: YoutubeDL, post_id: str) -> None:
    req = Request(
        f"https://www.patreon.com/api/posts/{post_id}/likes?json-api-version=1.0",
        data=b"{}",
        headers={"Content-Type": "application/vnd.api+json"},
        method="POST",
    )
    try:
        ydl.urlopen(req).read()
    except HTTPError as e:
        if e.status in (401, 403, 405):
            raise LikeRejected(f"Patreon returned HTTP {e.status} for the like request") from e
        raise


def like_watched(harvester, dry_run: bool = False) -> list[str]:
    """Like every downloaded post whose episode is watched in Plex and not yet liked."""
    state = harvester.state
    watched = watched_files(harvester.cfg)
    todo = []
    for post_id, post in state.posts.items():
        if post.get("status") != "done" or post.get("liked"):
            continue
        if any(Path(f) in watched for f in post.get("files", [])):
            todo.append(post_id)
    if not todo:
        return []
    log.info("%s: %d watched post(s) not liked yet", harvester.creator_name, len(todo))

    liked: list[str] = []
    with YoutubeDL(harvester._params()) as ydl:
        for i, post_id in enumerate(todo[:MAX_LIKES_PER_RUN]):
            if i:
                time.sleep(random.uniform(*PAUSE_BETWEEN_LIKES))
            title = state.posts[post_id].get("title")
            if _has_liked(ydl, post_id):
                log.info("Already liked %s: %s", post_id, title)
            elif dry_run:
                log.info("Would like %s: %s", post_id, title)
                continue
            else:
                like(ydl, post_id)
                if not _has_liked(ydl, post_id):
                    raise LikeRejected(f"like for {post_id} was accepted but did not stick")
                log.info("Liked %s: %s", post_id, title)
                liked.append(post_id)
            state.posts[post_id]["liked"] = True
            state.save()
    return liked
