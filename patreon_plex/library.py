"""Plex-style TV library layout and Kodi/Jellyfin/Infuse-compatible NFO sidecars."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .titles import safe_filename


@dataclass
class Episode:
    post_id: str
    show_folder: str  # e.g. "Mandy Cane Lane - Taskmaster"
    source_show: str | None  # e.g. "Taskmaster", None for misc posts
    season: int
    episode: int
    title: str
    description: str
    published: datetime
    url: str

    @property
    def season_dir(self) -> str:
        return f"Season {self.season:02d}" if self.season < 1000 else f"Season {self.season}"

    def basename(self, part: int | None = None) -> str:
        name = f"{self.show_folder} - S{self.season:02d}E{self.episode:02d}"
        if self.title:
            name += f" - {safe_filename(self.title, 100)}"
        if part:
            name += f" - pt{part}"
        return name


def write_episode_nfo(path: Path, ep: Episode) -> None:
    root = ET.Element("episodedetails")
    ET.SubElement(root, "title").text = ep.title or ep.published.strftime("%Y-%m-%d")
    ET.SubElement(root, "showtitle").text = ep.show_folder
    ET.SubElement(root, "season").text = str(ep.season)
    ET.SubElement(root, "episode").text = str(ep.episode)
    ET.SubElement(root, "aired").text = ep.published.strftime("%Y-%m-%d")
    ET.SubElement(root, "premiered").text = ep.published.strftime("%Y-%m-%d")
    ET.SubElement(root, "plot").text = ep.description
    uid = ET.SubElement(root, "uniqueid", type="patreon", default="true")
    uid.text = ep.post_id
    _write_xml(root, path)


def write_show_nfo(path: Path, title: str, plot: str) -> None:
    if path.exists():
        return
    root = ET.Element("tvshow")
    ET.SubElement(root, "title").text = title
    ET.SubElement(root, "plot").text = plot
    _write_xml(root, path)


def _write_xml(root: ET.Element, path: Path) -> None:
    ET.indent(root)
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
