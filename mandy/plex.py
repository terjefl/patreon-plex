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
    path: Path  # as this container sees it; for other sources, as Plex sees it
    local: bool = True  # under library_path, i.e. one of ours
    duration: float = 0.0  # seconds


def _get(cfg: Config, path: str) -> dict:
    plex = cfg.plex
    sep = "&" if "?" in path else "?"
    url = f"{plex.url.rstrip('/')}{path}{sep}{urllib.parse.urlencode({'X-Plex-Token': plex.token})}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["MediaContainer"]


def episodes(cfg: Config, include_other: bool = False) -> list[PlexEpisode]:
    """Episodes in the Plex library whose files are under library_path. With include_other, also
    the rest of the library (Mandy's YouTube videos from Pinchflat), as `local=False` with Plex's
    own path."""
    plex_root = cfg.plex.library_path.rstrip("/")
    result = []
    for item in _get(cfg, f"/library/sections/{cfg.plex.section_id}/allLeaves").get("Metadata", []):
        for media in item.get("Media", []):
            for part in media.get("Part", []):
                file = part.get("file", "")
                local = file.startswith(plex_root + "/")
                if not local and not include_other:
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
                        path=cfg.library_dir / file[len(plex_root) + 1 :] if local else Path(file),
                        local=local,
                        duration=(item.get("duration") or 0) / 1000,
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


def merge_stale_shows(cfg: Config, show_titles: dict[Path, str]) -> list[tuple[str, str]]:
    """After files moved to another show's folder, Plex can keep an episode under its old show.
    Merge each such old show into the show the episode's .nfo names, but only when every
    episode of the old show belongs there; a show only renamed gets its tvshow.nfo re-read.
    show_titles: episode path -> wanted show title. Returns (old show, new show) fixed."""
    plex_root = cfg.plex.library_path.rstrip("/")
    section = f"/library/sections/{cfg.plex.section_id}"
    shows = {s["title"]: s["ratingKey"] for s in _get(cfg, f"{section}/all").get("Metadata", [])}
    wants: dict[str, set] = {}
    titles: dict[str, str] = {}
    for item in _get(cfg, f"{section}/allLeaves").get("Metadata", []):
        file = item["Media"][0]["Part"][0]["file"]
        path = cfg.library_dir / file[len(plex_root) + 1:] if file.startswith(plex_root + "/") else None
        key = item.get("grandparentRatingKey")
        titles[key] = item.get("grandparentTitle", "")
        wants.setdefault(key, set()).add(show_titles.get(path, item.get("grandparentTitle", "")))
    merged = []
    for key, wanted in wants.items():
        if len(wanted) != 1:
            continue
        target = next(iter(wanted))
        if target == titles[key]:
            continue
        if target in shows:
            query = urllib.parse.urlencode({"ids": key, "X-Plex-Token": cfg.plex.token})
            url = f"{cfg.plex.url.rstrip('/')}/library/metadata/{shows[target]}/merge?{query}"
            urllib.request.urlopen(urllib.request.Request(url, method="PUT"), timeout=60).read()
        else:
            # the same show under a new spelling: have Plex re-read its tvshow.nfo
            refresh_metadata(cfg, key)
        merged.append((titles[key], target))
    return merged


def mark_unwatched(cfg: Config, rating_key: str) -> None:
    query = urllib.parse.urlencode(
        {"identifier": "com.plexapp.plugins.library", "key": rating_key, "X-Plex-Token": cfg.plex.token}
    )
    urllib.request.urlopen(f"{cfg.plex.url.rstrip('/')}/:/unscrobble?{query}", timeout=30).read()
