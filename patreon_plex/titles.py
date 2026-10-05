"""Parse post titles like "Taskmaster - S21 E1 - Cube Is Good" into show/season/episode."""

import re
from dataclasses import dataclass

# Matches "S21 E1", "S7E3", "S 2 E 10", "Season 2 Episode 3", "S1 Ep4" anywhere after the show name.
_SE_RE = re.compile(
    r"""^(?P<show>.+?)              # show name (lazy)
        [\s\-–—:|]*                 # separator
        \bS(?:eason)?\s*(?P<season>\d{1,3})
        \s*[.,x]?\s*
        E(?:p(?:isode)?)?\s*(?P<episode>\d{1,4})\b
        [\s\-–—:|.]*                # separator
        (?P<title>.*)$""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class ParsedTitle:
    show: str
    season: int
    episode: int
    episode_title: str


# Notes to patrons that aren't part of the title: "(Link Below)", "(link in description)", "⤵️".
_NOTE_RE = re.compile(r"\(\s*links?\b[^)]*\)|[⤵⬇👇]\ufe0f?", re.IGNORECASE)


def clean(text: str) -> str:
    text = _NOTE_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" -–—:|")


def parse_title(title: str) -> ParsedTitle | None:
    m = _SE_RE.match(clean(title))
    if not m:
        return None
    show = clean(m.group("show"))
    if not show:
        return None
    return ParsedTitle(
        show=show,
        season=int(m.group("season")),
        episode=int(m.group("episode")),
        episode_title=clean(m.group("title")).rstrip("."),
    )


def show_key(show: str) -> str:
    """Normalised key so 'Only Fools And Horses' and 'only fools and horses ' map to the same show."""
    return re.sub(r"[^a-z0-9]+", " ", show.casefold().replace("&", "and")).strip()


_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_filename(text: str, max_len: int = 150) -> str:
    """Make text safe for SMB/NAS filenames."""
    text = _UNSAFE.sub("", text.replace(":", " -").replace("/", "-"))
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    return text[:max_len].rstrip() or "Untitled"
