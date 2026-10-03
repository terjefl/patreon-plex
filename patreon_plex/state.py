import json
import os
from pathlib import Path


class State:
    """Persistent record of handled posts, show-name spellings and episode counters for unnumbered posts."""

    def __init__(self, path: Path):
        self.path = path
        data = json.loads(path.read_text()) if path.exists() else {}
        self.posts: dict[str, dict] = data.get("posts", {})
        self.shows: dict[str, str] = data.get("shows", {})
        self.counters: dict[str, int] = data.get("counters", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {"posts": self.posts, "shows": self.shows, "counters": self.counters},
                indent=2,
                ensure_ascii=False,
            )
        )
        os.replace(tmp, self.path)

    def is_settled(self, post_id: str, max_attempts: int) -> bool:
        post = self.posts.get(post_id)
        if not post:
            return False
        return post["status"] in ("done", "no_media", "no_access") or post.get("attempts", 0) >= max_attempts

    def next_number(self, counter: str) -> int:
        n = self.counters.get(counter, 0) + 1
        self.counters[counter] = n
        return n
