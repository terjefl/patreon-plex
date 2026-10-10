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


def test_public_video_list_has_links_but_nothing_private(tmp_path, monkeypatch):
    import json as _json

    from mandy import public_page, stats

    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="M", creator_name="Mandy Cane Lane")],
                 plex=PlexConfig(url="http://x", token="t", section_id=18))
    rows = [
        web.Row("Mandy Cane Lane", "Mandy Cane Lane - Hot Fuzz", 2023, 73, "HOT FUZZ - pt1", "2023-09-12", True, True,
                "https://www.patreon.com/posts/89651562", "http://plex/1", "1", duration=3000),
        web.Row("Mandy Cane Lane", "Mandy Cane Lane - Hot Fuzz", 2023, 73, "HOT FUZZ - pt2", "2023-09-12", True, True,
                "https://www.patreon.com/posts/89651562", "http://plex/2", "2", duration=2400),
        web.Row("Mandy Cane Lane", "Taskmaster", 11, 6, "Absolute Casserol", "2024-07-23", False, None,
                "https://www.patreon.com/posts/108645872", "", "", missing="Gitt opp", missing_detail="dailymotion: 401"),
        web.Row("Mandy Cane Lane", "Mandy Cane Lane - YouTube", 2026, 100999, "WALLY", "2026-10-09", True, None,
                "", "http://plex/3", "3", source="youtube", youtube_url="https://www.youtube.com/watch?v=gtitf4ECTzY"),
    ]
    (cfg.data_dir / "M").mkdir(parents=True)
    (cfg.data_dir / "M" / "youtube.json").write_text(_json.dumps({"checked": 0, "listed": ["gtitf4ECTzY", "old", "memb"], "videos": {
        "gtitf4ECTzY": {"kind": "video", "date": "2026-10-09", "duration": 1145, "title": "WALLY"},
        "old": {"kind": "live", "date": "2018-04-08", "duration": 7200, "title": "ARK </script> stream"},
        "memb": {"kind": "video", "date": "", "duration": 60, "title": "Members", "members_only": True}}}))
    entries = public_page.items(rows, cfg, cfg.creators[0])
    patreon = [e for e in entries if e["s"] == "patreon"]
    assert len(patreon) == 2 and patreon[0]["d"] == 5400 and patreon[0]["t"] == "HOT FUZZ"  # parts merged
    assert patreon[0]["show"] == "Hot Fuzz"
    assert [e["show"] for e in entries if e["s"] == "youtube"] == ["YouTube", "YouTube livestreams"]  # no members-only
    html = public_page.render_videos(rows, cfg, cfg.creators[0])
    assert "plex" not in html.casefold() and "Gitt opp" not in html and "dailymotion" not in html
    assert "watched" not in html.casefold() and "liked" not in html.casefold()
    assert "<\\/script>" in html and "ARK </script>" not in html  # titles can't break out of the data block
