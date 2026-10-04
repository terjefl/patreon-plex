import pytest

from patreon_plex.titles import parse_title, safe_filename, show_key


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

    from patreon_plex.library import Episode

    ep = Episode("1", "Show", "Show", "Show", 1, 4, "", "", datetime(2026, 1, 1, tzinfo=UTC), "")
    assert ep.display_title == "Episode 4"
    assert ep.basename() == "Show - S01E04"


def test_match_special():
    from patreon_plex.harvest import _match_special

    table = {"Dates": 8, "The Jolly Boys' Outing": 9, "Rodney Come Home": 10}
    assert _match_special(table, "The Jolly Boys' Outing (Special)") == ("The Jolly Boys' Outing", 9)
    assert _match_special(table, "Dates (1988)") == ("Dates", 8)
    assert _match_special(table, "Rodney Come Home") == ("Rodney Come Home", 10)
    assert _match_special(table, "Miami Twice") is None


def test_next_number_skips_reserved(tmp_path):
    from patreon_plex.state import State

    s = State(tmp_path / "state.json")
    assert s.next_number("special:x", {1, 2, 4}) == 3
    assert s.next_number("special:x", {1, 2, 4}) == 5
