import json
from pathlib import Path

from mandy.harvest import post_text
from mandy.library import set_episode_plot
from mandy.titles import clean_plot


def para(*nodes):
    return {"type": "paragraph", "content": list(nodes)}


def text(t, href=None):
    node = {"type": "text", "text": t}
    if href:
        node["marks"] = [{"type": "link", "attrs": {"href": href}}]
    return node


def test_post_text_drops_dividers_spacers_and_video_links():
    drive = "https://drive.google.com/file/d/1mOGpO4ug4F6ykI8_C9GWXJY41d4G9y2l/view?usp=sharing"
    doc = {"type": "doc", "content": [
        para(text("This was a fun one!")),
        para(text("----------------------------------------------------")),
        para(text(".")), para(text(".")),
        para({"type": "hardBreak"}),
        para(text("Part 1: "), text(drive[:40], href=drive)),
        para(text("Check my "), text("YouTube", href="https://youtube.com/channel/UC2o")),
    ]}
    assert post_text(json.dumps(doc)) == "This was a fun one!\n\nPart 1:\nCheck my YouTube"


def test_clean_plot_keeps_text_and_ellipses():
    raw = "Oh boy did he not prove the title! Lmao. ______________________\nMore soon...\n\n\n.\nBye"
    assert clean_plot(raw) == "Oh boy did he not prove the title! Lmao.\nMore soon...\n\nBye"


def test_no_text():
    assert post_text(None) == "" and clean_plot("-----\n.\n") == ""


def test_set_episode_plot(tmp_path):
    nfo = tmp_path / "ep.nfo"
    nfo.write_text('<?xml version="1.0" encoding="utf-8"?>\n<episodedetails><title>X</title><plot /></episodedetails>')
    assert set_episode_plot(nfo, "Hello ✨")
    assert "<plot>Hello ✨</plot>" in nfo.read_text()
    assert not set_episode_plot(nfo, "Hello ✨")


def test_remove_orphans_keeps_videos_and_recent_files(tmp_path):
    import os
    import time

    from mandy.config import Config, CreatorConfig
    from mandy.harvest import Harvester

    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c.txt", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="Someone")])
    season = tmp_path / "lib" / "Someone" / "Someone - Show" / "Season 01"
    season.mkdir(parents=True)
    (season.parent / "tvshow.nfo").write_text("x")
    for name in ("ep1.nfo", "ep1.mp4", "ep1.jpg", "ep2 - pt1.nfo", "ep2 - pt1.jpg", "ep3.nfo"):
        (season / name).write_text("x")
    old = time.time() - 2 * 86400
    for name in ("ep1.nfo", "ep2 - pt1.nfo", "ep2 - pt1.jpg"):
        os.utime(season / name, (old, old))

    removed = Harvester(cfg, cfg.creators[0], dry_run=True).remove_orphans()
    assert sorted(p.name for p in removed) == ["ep2 - pt1.jpg", "ep2 - pt1.nfo"]
    assert (season / "ep1.nfo").exists() and (season / "ep3.nfo").exists()  # has video / too recent
    assert (season.parent / "tvshow.nfo").exists()


def test_failed_download_leaves_no_sidecars_or_parts(tmp_path, monkeypatch):
    import pytest
    from yt_dlp.utils import DownloadError

    from mandy import harvest
    from mandy.config import Config, CreatorConfig

    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c.txt", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="Someone")])
    h = harvest.Harvester(cfg, cfg.creators[0], dry_run=True)
    monkeypatch.setattr(h, "_fetch_thumbnail", lambda info: None)
    monkeypatch.setattr(h, "_ensure_show_assets", lambda *a, **k: None)

    class FakeYDL:
        def __init__(self, params):
            self.params = params

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def process_ie_result(self, entry, download):
            if entry["url"].endswith("2"):
                raise DownloadError("ERROR: [dailymotion] x: HTTP Error 401")
            out = Path(self.params["paths"]["home"]) / (self.params["outtmpl"]["default"] % {"ext": "mp4"})
            out.write_text("video")
            out.with_suffix(".jpg").write_text("thumb")
            return {"requested_downloads": [{"filepath": str(out)}]}

    monkeypatch.setattr(harvest, "YoutubeDL", FakeYDL)
    info = {"_type": "playlist", "id": "7", "title": "Peep Show - S2 E3 - Local Hero", "timestamp": 1690000000,
            "entries": [{"_type": "url", "url": "https://dai.ly/1"}, {"_type": "url", "url": "https://dai.ly/2"}]}
    with pytest.raises(DownloadError):
        h.download(info)
    assert not [p for p in (tmp_path / "lib").rglob("*") if p.is_file()]


def test_empty_folder_puts_shows_at_the_library_root(tmp_path):
    from mandy.config import Config, CreatorConfig
    from mandy.harvest import Harvester

    root = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c.txt", data_dir=tmp_path / "data",
                  creators=[CreatorConfig(creator="M", creator_name="Mandy Cane Lane", folder="")])
    sub = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c.txt", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="M", creator_name="Mandy Cane Lane")])
    assert Harvester(root, root.creators[0], dry_run=True).library_dir == tmp_path / "lib"
    assert Harvester(sub, sub.creators[0], dry_run=True).library_dir == tmp_path / "lib" / "Mandy Cane Lane"


def test_refile_moves_a_post_to_its_proper_show(tmp_path):
    from mandy.config import Config, CreatorConfig
    from mandy.harvest import Harvester

    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c.txt", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="M", creator_name="Mandy Cane Lane", folder="")])
    old_show = tmp_path / "lib" / "Mandy Cane Lane - (Edit) Peep Show"
    (old_show / "Season 01").mkdir(parents=True)
    (old_show / "tvshow.nfo").write_text("x")
    old = []
    for part in (1, 2):
        stem = old_show / "Season 01" / f"Mandy Cane Lane - (Edit) Peep Show - S01E06 - - Funeral - Reaction! - pt{part}"
        for suffix in (".mp4", ".jpg", ".nfo"):
            stem.with_suffix(suffix).write_text(suffix)
        old.append(str(stem.with_suffix(".mp4")))
    h = Harvester(cfg, cfg.creators[0])
    h.state.posts["75018496"] = {"status": "done", "title": "(Edit) Peep Show - S1 E6* - Funeral - Reaction!",
                                 "published": 1669161600, "files": old}
    h.state.shows.update({"peep show": "Peep Show", "edit peep show": "(Edit) Peep Show"})
    moves = h.refile("75018496")
    season = tmp_path / "lib" / "Mandy Cane Lane - Peep Show" / "Season 01"
    assert [n.name for _, n in moves] == [f"Mandy Cane Lane - Peep Show - S01E06 - Funeral - Reaction! - pt{p}.mp4" for p in (1, 2)]
    assert all(n.exists() and n.with_suffix(".jpg").exists() for _, n in moves)
    assert "<title>Funeral - Reaction!</title>" in moves[0][1].with_suffix(".nfo").read_text()
    assert "<showtitle>Peep Show</showtitle>" in moves[0][1].with_suffix(".nfo").read_text()
    assert not old_show.exists() and "edit peep show" not in h.state.shows
    assert h.state.posts["75018496"]["files"] == [str(n) for _, n in moves]
    assert season.parent.joinpath("tvshow.nfo").exists()
    assert h.refile("75018496") == []  # already in place


def test_overrides_aliases_and_specials_place_posts(tmp_path):
    from mandy.config import Config, CreatorConfig
    from mandy.harvest import Harvester

    creator = CreatorConfig(
        creator="M", creator_name="Mandy Cane Lane", folder="",
        show_aliases={"WILTY? - Full Episode": "Would I Lie To You?"},
        specials={"Only Fools And Horses": {"Christmas Crackers": 1, "The Frog's Legacy": 7}},
        title_overrides={"1": "Only Fools And Horses - Christmas Crackers"},
    )
    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data", creators=[creator])
    h = Harvester(cfg, creator, dry_run=True)
    h.state.shows["only fools and horses"] = "Only Fools And Horses"
    plan = lambda pid, title: h.plan({"id": pid, "title": title, "timestamp": 1700000000})
    ep = plan("1", "Only Fools And Horses - S1 E7 - Christmas Crackers")
    assert (ep.show_title, ep.season, ep.episode, ep.title) == ("Only Fools And Horses", 0, 1, "Christmas Crackers")
    ep = plan("2", "Only Fools And Horses - The Frog's Legacy [1987 Christmas Special]")
    assert (ep.season, ep.episode, ep.title) == (0, 7, "The Frog's Legacy")
    ep = plan("3", "WILTY? - Full Episode - S9 E7")
    assert (ep.show_title, ep.season, ep.episode) == ("Would I Lie To You?", 9, 7)
    ep = plan("4", "Mr Bean - S1 - E13 - Goodnight Mr Bean")
    assert (ep.show_title, ep.season, ep.episode, ep.title) == ("Mr Bean", 1, 13, "Goodnight Mr Bean")
    ep = plan("5", "Mandy Cane Lane - Garth Marenghi's Darkplace - S01E01")
    assert ep.show_title == "Garth Marenghi's Darkplace"


def test_post_moving_to_specials_gets_a_number_of_its_own(tmp_path):
    from mandy.config import Config, CreatorConfig
    from mandy.harvest import Harvester

    creator = CreatorConfig(creator="M", creator_name="Mandy Cane Lane", folder="")
    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data", creators=[creator])
    h = Harvester(cfg, creator, dry_run=True)
    h.state.counters.update({"misc:2024": 5, "special:the office": 3})
    h.state.posts["9"] = {"status": "done", "number": 3, "counter": "misc:2024"}  # was misc 2024 #3
    h.state.shows["the office"] = "The Office"
    ep = h.plan({"id": "9", "title": "The Office - Deleted Scenes", "timestamp": 1704844800})
    assert (ep.season, ep.episode) == (0, 4)  # not S00E03, which is taken


def test_unofficial_special_on_an_official_number_moves_aside(tmp_path):
    from mandy.config import Config, CreatorConfig
    from mandy.harvest import Harvester

    creator = CreatorConfig(creator="M", creator_name="Mandy Cane Lane", folder="",
                            specials={"Taskmaster": {"New Year Treat 2025": 5}})
    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data", creators=[creator])
    h = Harvester(cfg, creator, dry_run=True)
    h.state.shows["taskmaster"] = "Taskmaster"
    h.state.counters["special:taskmaster"] = 6
    h.state.posts["7"] = {"status": "done", "number": 5, "counter": "special:taskmaster"}
    ep = h.plan({"id": "7", "title": "Taskmaster - 3 Balls On a Hill", "timestamp": 1666000000})
    assert (ep.season, ep.episode) == (0, 7)
