import pytest

from mandy.titles import clean, parse_title, safe_filename, show_key


@pytest.mark.parametrize(
    "title, show, season, episode, ep_title",
    [
        ("Garth Marenghi's Darkplace - S1 E4", "Garth Marenghi's Darkplace", 1, 4, ""),
        ("Only Fools And Horses - S7 E3 - Stage Fright", "Only Fools And Horses", 7, 3, "Stage Fright"),
        ("Only Fools And Horses- S7 E1 - The Sky's The Limit", "Only Fools And Horses", 7, 1, "The Sky's The Limit"),
        ("Taskmaster S20 E10 - Supping From The Fountain.", "Taskmaster", 20, 10, "Supping From The Fountain"),
        ("Taskmaster - S20 E9 - A 1970s Camping Kettle.", "Taskmaster", 20, 9, "A 1970s Camping Kettle"),
        ("Peep Show S2E3", "Peep Show", 2, 3, ""),
        ("Blackadder - Season 2 Episode 5 - Beer", "Blackadder", 2, 5, "Beer"),
    ],
)
def test_parse(title, show, season, episode, ep_title):
    p = parse_title(title)
    assert p is not None
    assert (p.show, p.season, p.episode, p.episode_title) == (show, season, episode, ep_title)


@pytest.mark.parametrize(
    "title",
    [
        "My Trip!",
        "My Trip (Part 2)",
        "Champion of Champions 4 - Put that on my gravestone.",
        "Only Fools And Horses - Rodney Come Home",
        "Season's greetings everyone",
    ],
)
def test_no_episode(title):
    assert parse_title(title) is None


def test_show_key():
    assert show_key("Only Fools & Horses") == show_key("only fools and  horses ")


def test_safe_filename():
    assert safe_filename('What? A "test": yes/no') == "What A test - yes-no"


def test_episode_display_title():
    from datetime import UTC, datetime

    from mandy.library import Episode

    ep = Episode("1", "Show", "Show", "Show", 1, 4, "", "", datetime(2026, 1, 1, tzinfo=UTC), "")
    assert ep.display_title == "Episode 4"
    assert ep.basename() == "Show - S01E04"


def test_match_special():
    from mandy.harvest import _match_special

    table = {"Dates": 8, "The Jolly Boys' Outing": 9, "Rodney Come Home": 10}
    assert _match_special(table, "The Jolly Boys' Outing (Special)") == ("The Jolly Boys' Outing", 9)
    assert _match_special(table, "Dates (1988)") == ("Dates", 8)
    assert _match_special(table, "Rodney Come Home") == ("Rodney Come Home", 10)
    assert _match_special(table, "Miami Twice") is None


def test_next_number_skips_reserved(tmp_path):
    from mandy.state import State

    s = State(tmp_path / "state.json")
    assert s.next_number("special:x", {1, 2, 4}) == 3
    assert s.next_number("special:x", {1, 2, 4}) == 5


def test_config_throttle(tmp_path):
    from mandy.config import load_config

    p = tmp_path / "c.yaml"
    p.write_text("library_dir: /l\ncookies_file: /c\ndata_dir: /d\nrate_limit: 4M\npause_seconds: [60, 180]\ncreators:\n  - creator: X\n")
    cfg = load_config(p)
    assert cfg.rate_limit == "4M" and cfg.pause_seconds == (60, 180)
    p.write_text("library_dir: /l\ncookies_file: /c\ndata_dir: /d\ncreators:\n  - creator: X\n")
    assert load_config(p).pause_seconds == (0, 0)


@pytest.mark.parametrize(
    "raw, cleaned",
    [
        ("Peep Show - S3 E5 - Jurying (Link Below)", "Peep Show - S3 E5 - Jurying"),
        ("Peep Show - S2 E3 - Local Hero (link in description) ", "Peep Show - S2 E3 - Local Hero"),
        ("Kevin Bridges - If Facebook Were a Pub ⤵️", "Kevin Bridges - If Facebook Were a Pub"),
        ("Big Fat Quiz (2016) - PART 1", "Big Fat Quiz (2016) - PART 1"),
    ],
)
def test_clean_drops_link_notes(raw, cleaned):
    assert clean(raw) == cleaned


def test_link_note_not_in_episode_title():
    assert parse_title("Peep Show - S2 E3 - Local Hero (Link Below)").episode_title == "Local Hero"


def test_video_entries_prefers_patreon_copy():
    from mandy.harvest import _video_entries

    embed = {"_type": "url", "url": "https://dai.ly/k7plojWDtkI8knBgoss"}
    native = {"id": "1", "formats": [{"url": "https://stream.mux.com/x.m3u8"}]}
    assert _video_entries({"_type": "playlist", "entries": iter([embed, native])}) == [native]
    assert _video_entries({"_type": "playlist", "entries": [embed]}) == [embed]
    assert _video_entries(native) == [native]


def test_tag_before_show_and_star_after_episode():
    p = parse_title("(Edit) Peep Show - S1 E6* - Funeral - Reaction!")
    assert (p.show, p.season, p.episode, p.episode_title) == ("Peep Show", 1, 6, "Funeral - Reaction!")
