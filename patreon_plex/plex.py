"""Read episodes and watched status from the Plex library section."""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import Config


@dataclass
class PlexEpisode:
    rating_key: str
    show: str
    season: int
    episode: int
    title: str
    aired: str  # YYYY-MM-DD
    watched: bool
    path: Path  # as this container sees it


def _get(cfg: Config, path: str) -> dict:
    plex = cfg.plex
    sep = "&" if "?" in path else "?"
    url = f"{plex.url.rstrip('/')}{path}{sep}{urllib.parse.urlencode({'X-Plex-Token': plex.token})}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["MediaContainer"]


def episodes(cfg: Config) -> list[PlexEpisode]:
    plex_root = cfg.plex.library_path.rstrip("/")
    result = []
    for item in _get(cfg, f"/library/sections/{cfg.plex.section_id}/allLeaves").get("Metadata", []):
        for media in item.get("Media", []):
            for part in media.get("Part", []):
                file = part.get("file", "")
                if not file.startswith(plex_root + "/"):
                    continue
                result.append(
                    PlexEpisode(
                        rating_key=str(item["ratingKey"]),
                        show=item.get("grandparentTitle", ""),
                        season=int(item.get("parentIndex", 0)),
                        episode=int(item.get("index", 0)),
                        title=item.get("title", ""),
                        aired=item.get("originallyAvailableAt", ""),
                        watched=bool(item.get("viewCount")),
                        path=cfg.library_dir / file[len(plex_root) + 1 :],
                    )
                )
    return result


@lru_cache(maxsize=4)
def machine_id(url: str, token: str) -> str:
    req = urllib.request.Request(
        f"{url.rstrip('/')}/identity?{urllib.parse.urlencode({'X-Plex-Token': token})}",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["MediaContainer"]["machineIdentifier"]


def web_link(cfg: Config, rating_key: str) -> str:
    server = machine_id(cfg.plex.url, cfg.plex.token)
    key = urllib.parse.quote(f"/library/metadata/{rating_key}", safe="")
    return f"https://app.plex.tv/desktop/#!/server/{server}/details?key={key}"


def mark_watched(cfg: Config, rating_key: str) -> None:
    query = urllib.parse.urlencode(
        {"identifier": "com.plexapp.plugins.library", "key": rating_key, "X-Plex-Token": cfg.plex.token}
    )
    urllib.request.urlopen(f"{cfg.plex.url.rstrip('/')}/:/scrobble?{query}", timeout=30).read()


def refresh_metadata(cfg: Config, rating_key: str) -> None:
    """Have Plex re-read an item's metadata (with the NFO agent: its .nfo sidecar)."""
    query = urllib.parse.urlencode({"X-Plex-Token": cfg.plex.token})
    url = f"{cfg.plex.url.rstrip('/')}/library/metadata/{rating_key}/refresh?{query}"
    urllib.request.urlopen(urllib.request.Request(url, method="PUT"), timeout=30).read()


def mark_unwatched(cfg: Config, rating_key: str) -> None:
    query = urllib.parse.urlencode(
        {"identifier": "com.plexapp.plugins.library", "key": rating_key, "X-Plex-Token": cfg.plex.token}
    )
    urllib.request.urlopen(f"{cfg.plex.url.rstrip('/')}/:/unscrobble?{query}", timeout=30).read()
