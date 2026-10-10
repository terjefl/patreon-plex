from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


@dataclass
class PlexConfig:
    url: str
    token: str
    section_id: int
    library_path: str = "/Media01/Mandy"  # library_dir as Plex sees it


@dataclass
class CreatorConfig:
    creator: str  # slug from patreon.com/c/<creator>
    creator_name: str | None = None
    folder: str | None = None  # subfolder of library_dir; defaults to creator_name or slug; "" = library_dir itself
    since: date | None = None
    max_downloads_per_run: int = 0
    show_name_template: str = "{creator} - {show}"  # folder name
    show_title_template: str = "{show}"  # title shown in Plex
    misc_show_name: str = "{creator}"
    show_aliases: dict[str, str] = field(default_factory=dict)
    # Official special numbers per show, e.g. {"Only Fools And Horses": {"Dates": 8}}
    specials: dict[str, dict[str, int]] = field(default_factory=dict)
    # Title to file a post by instead of its own, per post id, when its title can't say where it
    # belongs, e.g. {"83877577": "Travel Man - S2 E3 - Copenhagen (Noel Fielding)"}
    title_overrides: dict[str, str] = field(default_factory=dict)
    # The creator's YouTube channel (e.g. https://www.youtube.com/@MandyCaneLane), for the statistics page
    youtube_url: str | None = None

    @property
    def campaign_url(self) -> str:
        return f"https://www.patreon.com/c/{self.creator}/posts"

    @property
    def folder_name(self) -> str:
        return self.folder if self.folder is not None else (self.creator_name or self.creator)


@dataclass
class Config:
    library_dir: Path
    cookies_file: Path
    data_dir: Path
    creators: list[CreatorConfig]
    interval_minutes: int = 60
    # Throttling, so a backlog doesn't look like a scraper: max download speed
    # (yt-dlp syntax, e.g. "4M" = 4 MiB/s) and a random pause between videos.
    rate_limit: str | None = None
    pause_seconds: tuple[int, int] = (0, 0)
    heartbeat_url: str | None = None
    web_port: int | None = 8000  # index page (needs `plex`); None to disable
    plex: PlexConfig | None = None

    def find_creator(self, slug: str) -> CreatorConfig:
        for c in self.creators:
            if c.creator.casefold() == slug.casefold():
                return c
        raise SystemExit(f"No creator {slug!r} in config")


def _creator(raw: dict) -> CreatorConfig:
    since = raw.pop("since", None)
    if isinstance(since, str):
        since = date.fromisoformat(since)
    return CreatorConfig(**raw, since=since)


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text()) or {}
    plex = raw.pop("plex", None)
    creators = [_creator(c) for c in raw.pop("creators", [])]
    if not creators:
        raise SystemExit("Config needs at least one entry under 'creators'")
    for key in ("library_dir", "cookies_file", "data_dir"):
        raw[key] = Path(raw[key])
    pause = raw.pop("pause_seconds", None)
    if isinstance(pause, (int, float)):
        pause = (pause, pause)
    return Config(
        **raw,
        pause_seconds=tuple(pause) if pause else (0, 0),
        creators=creators,
        plex=PlexConfig(**plex) if plex and plex.get("token") else None,
    )
