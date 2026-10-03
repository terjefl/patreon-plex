from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


@dataclass
class PlexConfig:
    url: str
    token: str
    section_id: int


@dataclass
class Config:
    creator: str
    library_dir: Path
    cookies_file: Path
    data_dir: Path
    creator_name: str | None = None
    since: date | None = None
    interval_minutes: int = 60
    show_name_template: str = "{creator} - {show}"
    misc_show_name: str = "{creator}"
    show_aliases: dict[str, str] = field(default_factory=dict)
    max_downloads_per_run: int = 0
    heartbeat_url: str | None = None
    plex: PlexConfig | None = None

    @property
    def campaign_url(self) -> str:
        return f"https://www.patreon.com/c/{self.creator}/posts"


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text()) or {}
    plex = raw.pop("plex", None)
    since = raw.pop("since", None)
    if isinstance(since, str):
        since = date.fromisoformat(since)
    for key in ("library_dir", "cookies_file", "data_dir"):
        raw[key] = Path(raw[key])
    return Config(
        **raw,
        since=since,
        plex=PlexConfig(**plex) if plex and plex.get("token") else None,
    )
