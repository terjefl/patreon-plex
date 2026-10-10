import json
import re

from patreon_plex import plex, stats, stats_page
from patreon_plex.config import Config, CreatorConfig, PlexConfig


def cfg_for(tmp_path, **creator):
    return Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c", data_dir=tmp_path / "data",
                  creators=[CreatorConfig(creator="M", creator_name="Mandy Cane Lane", **creator)],
                  plex=PlexConfig(url="http://x", token="t", section_id=18, library_path="/Media01/Patreon"))


def test_aggregate_by_month_year_and_kind():
    data = stats.aggregate([("patreon", "2023-01-05", 3600), ("patreon", "2023-01-20", 1800),
                            ("video", "2023-02-01", 600), ("live", "2018-04-01", 7200)])
    assert data["months"]["2023-01"]["patreon"] == [2, 5400]
    assert data["years"]["2023"]["video"] == [1, 600]
    assert data["total"]["live"] == [1, 7200] and list(data["years"]) == ["2018", "2023"]


def test_patreon_post_in_parts_counts_once(tmp_path, monkeypatch):
    cfg = cfg_for(tmp_path)
    lib = cfg.library_dir
    state = {"posts": {
        "1": {"status": "done", "published": 1672531200, "files": [str(lib / "a - pt1.mp4"), str(lib / "a - pt2.mp4")]},
        "2": {"status": "failed", "published": 1672531200},
    }}
    (cfg.data_dir / "M").mkdir(parents=True)
    (cfg.data_dir / "M" / "state.json").write_text(json.dumps(state))
    monkeypatch.setattr(plex, "episodes", lambda cfg, section=None, include_other=False: [
        plex.PlexEpisode("1", "S", 1, 1, "a", "", False, lib / "a - pt1.mp4", duration=1500),
        plex.PlexEpisode("2", "S", 1, 2, "a", "", False, lib / "a - pt2.mp4", duration=1300),
    ])
    assert stats.collect(cfg, cfg.creators[0]) == [("patreon", "2023-01-01", 2800)]


class FakeYDL:
    lookups: list = []

    def __init__(self, params):
        self.flat = params.get("extract_flat")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download, process=True):
        if self.flat:
            tab = url.rsplit("/", 1)[1]
            entries = {"videos": [{"id": "v1", "duration": 600}, {"id": "v2", "duration": 900}],
                       "streams": [{"id": "s1", "duration": 7200}]}.get(tab)
            if entries is None:
                raise stats.DownloadError("This channel does not have a shorts tab")
            return {"entries": entries}
        vid = url.rsplit("=", 1)[1]
        FakeYDL.lookups.append(vid)
        return {"upload_date": {"v1": "20240105", "v2": "20240210", "s1": "20180401"}[vid], "duration": None}


def test_youtube_refresh_looks_up_only_new_videos(tmp_path, monkeypatch):
    cfg = cfg_for(tmp_path, youtube_url="https://www.youtube.com/@Mandy")
    monkeypatch.setattr(stats, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(stats, "PAUSE_BETWEEN_VIDEOS", 0)
    FakeYDL.lookups = []
    assert stats.refresh_youtube(cfg, cfg.creators[0], max_new=2) == 1  # one left for the next run
    assert stats.refresh_youtube(cfg, cfg.creators[0]) == 0
    assert sorted(FakeYDL.lookups) == ["s1", "v1", "v2"]  # each looked up once
    catalog = stats.load_youtube(cfg, cfg.creators[0])
    assert catalog["videos"]["s1"] == {"kind": "live", "date": "2018-04-01", "duration": 7200, "title": ""}
    assert not stats.youtube_due(cfg, cfg.creators[0])


def test_stats_page_is_public_safe_and_in_english(tmp_path, monkeypatch):
    cfg = cfg_for(tmp_path)
    items = [("patreon", "2022-10-20", 3000), ("patreon", "2023-01-02", 5400), ("video", "2023-01-03", 900),
             ("live", "2018-03-01", 10800)]
    monkeypatch.setattr(stats_page, "collect", lambda cfg, creator: items)
    html = stats_page.render_stats(cfg, cfg.creators[0])
    assert "<title>Mandy Cane Lane in numbers</title>" in html and 'lang="en"' in html
    assert "2 videos since Oct 2022" in html and "2 h 20 m" in html  # Patreon total: 50 + 90 minutes
    assert "plex" not in html.casefold() and "watched" not in html.casefold()
    assert len(re.findall(r'class="hit"', html)) == 4  # Oct 2022 .. Jan 2023
