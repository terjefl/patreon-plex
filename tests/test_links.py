import io
import json

import pytest
from yt_dlp.networking.exceptions import TransportError
from yt_dlp.utils import DownloadError

from patreon_plex.config import Config, CreatorConfig
from patreon_plex.harvest import Harvester, linked_videos


def doc(*paragraphs):
    return json.dumps({"type": "doc", "content": [{"type": "paragraph", "content": p} for p in paragraphs]})


def link(href, text=None):
    return {"type": "text", "text": text or href, "marks": [{"type": "link", "attrs": {"href": href}}]}


def test_drive_link_as_href_and_text_counts_once():
    url = "https://drive.google.com/file/d/1mOGpO4ug4F6ykI8_C9GWXJY41d4G9y2l/view?usp=sharing"
    content = doc([{"type": "text", "text": "This was a fun one!"}], [link(url, url[:45])])
    assert linked_videos(content) == [url]


def test_parts_keep_their_order():
    content = doc(
        [{"type": "text", "text": "Part 1: https://dai.ly/k266hY9DRhEgrfA06Ho."}],
        [link("https://www.dailymotion.com/video/x8abc12")],
    )
    assert linked_videos(content) == ["https://dai.ly/k266hY9DRhEgrfA06Ho", "https://www.dailymotion.com/video/x8abc12"]


def test_other_links_are_ignored():
    content = doc([link("https://youtube.com/channel/UC2oLKkL2ry-m7ZrtdbfFPbw"), link("https://www.patreon.com/posts/1")])
    assert linked_videos(content) == []


def test_no_text():
    assert linked_videos(None) == []


class FakeYDL:
    def __init__(self, post):
        self.post = post

    def extract_info(self, url, download, process):
        raise DownloadError("ERROR: [patreon] 82632202: No supported media found in this post")

    def urlopen(self, request):
        return io.BytesIO(json.dumps({"data": {"attributes": self.post}}).encode())


def harvester(tmp_path):
    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c.txt", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="Someone")])
    return Harvester(cfg, cfg.creators[0], dry_run=True)


def test_post_with_linked_video_becomes_a_playlist(tmp_path):
    url = "https://drive.google.com/file/d/1mOGpO4ug4F6ykI8_C9GWXJY41d4G9y2l/view?usp=sharing"
    post = {"title": "Peep Show - S3 E5 - Jurying (Link Below)", "published_at": "2023-01-05T18:00:00.000+00:00",
            "url": "https://www.patreon.com/posts/peep-show-s3-e5-82632202", "content_json_string": doc([link(url)])}
    info = harvester(tmp_path)._extract_post(FakeYDL(post), "82632202")
    assert info["_type"] == "playlist"
    assert info["title"] == post["title"]
    assert info["timestamp"] == 1672941600
    assert info["entries"] == [{"_type": "url_transparent", "url": url}]


def test_post_without_links_stays_no_media(tmp_path):
    post = {"title": "Poll time!", "published_at": "2023-01-05T18:00:00.000+00:00", "content_json_string": doc([])}
    with pytest.raises(DownloadError, match="No supported media"):
        harvester(tmp_path)._extract_post(FakeYDL(post), "1")


def test_failed_lookup_is_retried_not_no_media(tmp_path):
    class Offline(FakeYDL):
        def urlopen(self, request):
            raise TransportError("connection reset")

    with pytest.raises(DownloadError, match="Could not look for video links"):
        harvester(tmp_path)._extract_post(Offline({}), "1")


def test_no_media_error_from_ytdlp_is_quiet(caplog):
    from patreon_plex.harvest import _YtdlpLogger

    caplog.set_level("DEBUG", logger="patreon_plex.harvest")
    _YtdlpLogger().error("ERROR: [patreon] 1: No supported media found in this post")
    _YtdlpLogger().error("ERROR: [GoogleDrive] x: HTTP Error 429")
    assert [r.levelname for r in caplog.records] == ["DEBUG", "ERROR"]
