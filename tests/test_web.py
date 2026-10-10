import re
from pathlib import Path

from patreon_plex import plex, web
from patreon_plex.config import Config, CreatorConfig, PlexConfig


def test_chronological_page_is_newest_first_across_shows(tmp_path, monkeypatch):
    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="M", creator_name="Mandy")],
                 plex=PlexConfig(url="http://x", token="t", section_id=1))
    eps = [("Taskmaster", 5, 1, "Dignity", "2023-04-05", False), ("Peep Show", 3, 1, "Mugging", "2023-03-28", True),
           ("Mandy", 2023, 30, "Big Fat Quiz", "2023-04-04", False), ("Taskmaster", 21, 1, "Cube", "2026-10-01", True)]
    files = [Path(tmp_path / f"{i}.mp4") for i in range(len(eps))]
    monkeypatch.setattr(plex, "episodes", lambda cfg, section=None: [
        plex.PlexEpisode(str(10 + i), show, s, e, t, d, w, files[i]) for i, (show, s, e, t, d, w) in enumerate(eps)
    ])
    monkeypatch.setattr(plex, "web_link", lambda cfg, key: "http://plex/" + key)
    monkeypatch.setattr(web, "post_files", lambda posts: {f: str(i) for i, f in enumerate(files)})

    html = web.render_chrono(web.Index(cfg))
    assert re.findall(r"<h2>(.*?)</h2>", html) == ["Oktober 2026", "April 2023", "Mars 2023"]
    titles = re.findall(r'<span class="show">[^<]*</span> ([^<]*)</td>', html)
    assert titles == ["Cube", "Dignity", "Big Fat Quiz", "Mugging"]
    assert '<body class="f-unwatched" data-page="chrono">' in html


def test_each_creator_reads_its_own_plex_library(tmp_path, monkeypatch):
    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="A", creator_name="Ann"),
                           CreatorConfig(creator="B", creator_name="Bo", plex_section_id=30)],
                 plex=PlexConfig(url="http://x", token="t", section_id=18))
    files = {18: tmp_path / "a.mp4", 30: tmp_path / "b.mp4"}
    asked = []

    def episodes(cfg, section=None):
        asked.append(section)
        return [plex.PlexEpisode(str(section), f"Show {section}", 1, 1, "Ep", "2026-10-01", False, files[section])]

    monkeypatch.setattr(plex, "episodes", episodes)
    monkeypatch.setattr(plex, "web_link", lambda cfg, key: "http://plex/" + key)
    by_creator = {"A": {files[18]: "1"}, "B": {files[30]: "2"}}
    monkeypatch.setattr(web, "State", lambda path: type("S", (), {"posts": path.parent.name})())
    monkeypatch.setattr(web, "post_files", lambda creator: by_creator[creator])
    monkeypatch.setattr(web, "_missing_rows", lambda *a: [])

    rows = web.Index(cfg).rows()
    assert sorted(asked) == [18, 30]
    assert sorted((r.creator, r.show) for r in rows) == [("Ann", "Show 18"), ("Bo", "Show 30")]
    assert cfg.section_for(cfg.creators[0]) == 18 and cfg.section_for(cfg.creators[1]) == 30
