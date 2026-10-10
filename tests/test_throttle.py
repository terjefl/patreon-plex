import time

from mandy.config import Config, CreatorConfig
from mandy.harvest import THROTTLE_WAIT, THROTTLE_WAIT_MAX, Harvester, _linked_hosts, _YtdlpLogger


def harvester(tmp_path):
    cfg = Config(library_dir=tmp_path / "lib", cookies_file=tmp_path / "c.txt", data_dir=tmp_path / "data",
                 creators=[CreatorConfig(creator="Someone")])
    return Harvester(cfg, cfg.creators[0], dry_run=True)


def test_throttle_waits_double_and_keep_attempts(tmp_path):
    h = harvester(tmp_path)
    waits = []
    for _ in range(8):
        h._record_error("1", "ERROR: [GoogleDrive] x: HTTP Error 429: Too Many Requests")
        waits.append(h.state.posts["1"]["retry_after"] - time.time())
    post = h.state.posts["1"]
    assert post["status"] == "failed" and "attempts" not in post
    assert abs(waits[0] - THROTTLE_WAIT) < 5 and abs(waits[1] - 2 * THROTTLE_WAIT) < 5
    assert abs(waits[-1] - THROTTLE_WAIT_MAX) < 5
    assert not h.state.is_settled("1", 5)


def test_drive_quota_page_counts_as_throttled(tmp_path):
    h = harvester(tmp_path)
    h.ytdlp_logger.warning("[GoogleDrive] Too many users have viewed or downloaded this file recently.")
    assert h.ytdlp_logger.throttled
    h._record_error("2", "ERROR: Postprocessing: Invalid data found when processing input", throttled=True)
    assert "retry_after" in h.state.posts["2"]


def test_other_errors_still_use_up_attempts(tmp_path):
    h = harvester(tmp_path)
    h._record_error("3", "ERROR: [dailymotion] k1: Not found.")
    assert h.state.posts["3"]["attempts"] == 1 and "retry_after" not in h.state.posts["3"]
    assert not _YtdlpLogger().throttled


def test_linked_hosts():
    info = {"entries": [{"_type": "url_transparent", "url": "https://drive.google.com/file/d/x/view"},
                        {"_type": "url_transparent", "url": "https://dai.ly/k1"}]}
    assert _linked_hosts(info) == {"drive.google.com", "dailymotion.com"}
    assert _linked_hosts({"id": "1"}) == set()


def test_embedded_drive_video_counts_as_drive():
    info = {"_type": "url_transparent", "id": "74529766", "url": "https://drive.google.com/file/d/1mlS/view"}
    assert _linked_hosts(info) == {"drive.google.com"}
    assert _linked_hosts({"_type": "video", "url": "https://c10.patreonusercontent.com/x.mp4"}) == set()
