import re
from pathlib import Path

from mandy import plex, web
from mandy.config import Config, CreatorConfig, PlexConfig


def test_chronological_page_is_newest_first_across_shows(tmp_path, monkeypatch):
    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="M", creator_name="Mandy")],
                 plex=PlexConfig(url="http://x", token="t", section_id=1))
    eps = [("Taskmaster", 5, 1, "Dignity", "2023-04-05", False), ("Peep Show", 3, 1, "Mugging", "2023-03-28", True),
           ("Mandy", 2023, 30, "Big Fat Quiz", "2023-04-04", False), ("Taskmaster", 21, 1, "Cube", "2026-10-01", True)]
    files = [Path(tmp_path / f"{i}.mp4") for i in range(len(eps))]
    monkeypatch.setattr(plex, "episodes", lambda cfg, section=None, include_other=False: [
        plex.PlexEpisode(str(10 + i), show, s, e, t, d, w, files[i]) for i, (show, s, e, t, d, w) in enumerate(eps)
    ])
    monkeypatch.setattr(plex, "web_link", lambda cfg, key: "http://plex/" + key)
    monkeypatch.setattr(web, "post_files", lambda posts: {f: str(i) for i, f in enumerate(files)})

    html = web.render_chrono(web.Index(cfg))
    assert re.findall(r"<h2>(.*?)</h2>", html) == ["Oktober 2026", "April 2023", "Mars 2023"]
    titles = re.findall(r'<span class="show">[^<]*</span> ([^<]*)</td>', html)
    assert titles == ["Cube", "Dignity", "Big Fat Quiz", "Mugging"]
    assert '<body class="f-unwatched" data-page="chrono">' in html


def test_youtube_episodes_in_the_creators_library_are_listed_with_a_youtube_link(tmp_path, monkeypatch):
    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="M", creator_name="Mandy Cane Lane")],
                 plex=PlexConfig(url="http://x", token="t", section_id=18))
    patreon_file = tmp_path / "p.mp4"
    yt_file = Path("/Media01/Pinchflat/TV/Mandy Cane Lane - YouTube/Season 2026/s2026e100999 - WALLY [gtitf4ECTzY].mp4")
    monkeypatch.setattr(plex, "episodes", lambda cfg, section=None, include_other=False: [
        plex.PlexEpisode("1", "Taskmaster", 21, 1, "Cube", "2026-10-01", True, patreon_file),
        plex.PlexEpisode("2", "Mandy Cane Lane - YouTube", 2026, 100999, "WALLY", "2026-10-09", False, yt_file, local=False),
    ][: 2 if include_other else 1])
    monkeypatch.setattr(plex, "web_link", lambda cfg, key: "http://plex/" + key)
    monkeypatch.setattr(web, "post_files", lambda posts: {patreon_file: "9"})

    html = web.render_chrono(web.Index(cfg))
    assert "<title>Mandy Cane Lane</title>" in html and "<h1>Mandy Cane Lane</h1>" in html
    assert "2 episoder (1 Patreon · 1 YouTube)" in html
    yt_row = re.search(r'<tr class="yt[^"]*".*?</tr>', html).group(0)
    assert "https://www.youtube.com/watch?v=gtitf4ECTzY" in yt_row and "Sjekk på YouTube" in yt_row and '<span class="show">YouTube</span>' in yt_row
    assert "patreon.com" not in yt_row and "http://plex/2" in yt_row
    assert 'name="src"' in html
