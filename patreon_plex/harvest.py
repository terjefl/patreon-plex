import json
import logging
import re
import shutil
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import DownloadError

from .config import Config, CreatorConfig
from .library import Episode, write_episode_nfo, write_show_nfo
from .state import State
from .titles import clean, parse_title, safe_filename, show_key

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
# Stop paging through the (newest-first) post list after this many already handled posts in a row.
STOP_AFTER_KNOWN = 25
# ...or this many posts in a row older than `since`.
STOP_AFTER_OLD = 5


class LoginExpired(Exception):
    pass


@dataclass
class RunResult:
    downloaded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    pending: int = 0


class Harvester:
    def __init__(self, cfg: Config, creator: CreatorConfig, dry_run: bool = False):
        self.cfg = cfg
        self.creator = creator
        work_dir = cfg.data_dir / creator.creator
        work_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir = work_dir / "tmp"
        self.library_dir = cfg.library_dir / safe_filename(creator.folder_name)
        # yt-dlp writes refreshed cookies back to the cookie file, so work on a copy
        # and leave the (possibly read-only) mounted original alone.
        self.cookies = work_dir / "cookies.txt"
        self.state = State(work_dir / "state.json")
        if dry_run:
            self.state.save = lambda: None
        self.creator_name = creator.creator_name or creator.creator
        self.creator_avatar: str | None = None

    def _params(self, **extra) -> dict:
        return {
            "cookiefile": str(self.cookies),
            "quiet": True,
            "noprogress": True,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": 4,
            "logger": log,
            **extra,
        }

    def refresh_cookies(self) -> None:
        shutil.copyfile(self.cfg.cookies_file, self.cookies)

    def check_login(self) -> str:
        """Return the logged-in user's name, or raise LoginExpired."""
        with YoutubeDL(self._params()) as ydl:
            try:
                resp = ydl.urlopen(Request("https://www.patreon.com/api/current_user?fields[user]=full_name"))
            except HTTPError as e:
                if e.status in (401, 403):
                    raise LoginExpired(f"Patreon returned HTTP {e.status} for current_user") from e
                raise
            return json.loads(resp.read())["data"]["attributes"].get("full_name", "?")

    # ---- planning ----------------------------------------------------------

    def _canonical_show(self, raw: str) -> str:
        aliases = {show_key(k): v for k, v in self.creator.show_aliases.items()}
        key = show_key(raw)
        if key in aliases:
            return aliases[key]
        # First spelling seen wins, so typos in later titles don't create new shows.
        return self.state.shows.setdefault(key, raw)

    def plan(self, info: dict) -> Episode:
        post_id = str(info["id"])
        title = clean(info.get("title") or "")
        published = datetime.fromtimestamp(info["timestamp"], tz=UTC)
        description = info.get("description") or ""
        post_state = self.state.posts.setdefault(post_id, {"status": "pending"})

        def numbered(counter: str) -> int:
            # Assigned once per post and remembered, so retries keep the same number.
            if "number" not in post_state:
                post_state["number"] = self.state.next_number(counter)
            return post_state["number"]

        parsed = parse_title(title)
        special_show = self._known_show_prefix(title)
        if parsed:
            show = self._canonical_show(parsed.show)
            season, episode, ep_title = parsed.season, parsed.episode, parsed.episode_title
        elif special_show:
            # "Only Fools And Horses - Dates (1988)": a known show without SxE goes to Specials.
            show = special_show
            season, episode, ep_title = 0, numbered(f"special:{show_key(show)}"), clean(title.split(" - ", 1)[1])
        else:
            # Everything else: one season per year, numbered in publishing order.
            show = None
            season, episode, ep_title = published.year, numbered(f"misc:{published.year}"), title

        if show:
            folder = self.creator.show_name_template.format(creator=self.creator_name, show=show)
        else:
            folder = self.creator.misc_show_name.format(creator=self.creator_name)
        return Episode(
            post_id=post_id,
            show_folder=safe_filename(folder),
            source_show=show,
            season=season,
            episode=episode,
            title=ep_title,
            description=description,
            published=published,
            url=info.get("webpage_url") or "",
        )

    def _known_show_prefix(self, title: str) -> str | None:
        if " - " not in title:
            return None
        key = show_key(title.split(" - ", 1)[0])
        aliases = {show_key(k): v for k, v in self.creator.show_aliases.items()}
        return aliases.get(key) or self.state.shows.get(key)

    # ---- listing -----------------------------------------------------------

    def collect(self, limit: int | None = None) -> list[dict]:
        """Return full info dicts for unhandled posts, oldest first."""
        candidates: list[dict] = []
        known_streak = old_streak = 0
        with YoutubeDL(self._params(extract_flat="in_playlist")) as ydl:
            playlist = ydl.extract_info(self.creator.campaign_url, download=False, process=False)
            self.creator_name = (
                self.creator.creator_name or playlist.get("uploader") or playlist.get("title") or self.creator.creator
            )
            self.creator_avatar = playlist.get("thumbnail")
            for entry in playlist["entries"]:
                post_id = _post_id(entry)
                if limit is None and self.state.is_settled(post_id, MAX_ATTEMPTS):
                    known_streak += 1
                    if known_streak >= STOP_AFTER_KNOWN:
                        break
                    continue
                known_streak = 0
                try:
                    info = ydl.extract_info(f"https://www.patreon.com/posts/{post_id}", download=False, process=False)
                except DownloadError as e:
                    self._record_error(post_id, str(e))
                    continue
                published = datetime.fromtimestamp(info["timestamp"], tz=UTC).date()
                if self.creator.since and published < self.creator.since:
                    old_streak += 1
                    if old_streak >= STOP_AFTER_OLD:
                        break
                    continue
                old_streak = 0
                candidates.append(info)
                if limit and len(candidates) >= limit:
                    break
        return list(reversed(candidates))

    def _record_error(self, post_id: str, message: str) -> None:
        post = self.state.posts.setdefault(post_id, {"status": "pending"})
        if "No supported media" in message:
            post["status"] = "no_media"
            log.info("Post %s has no video, skipping", post_id)
        elif "do not have access" in message:
            self.check_login()  # raises LoginExpired if the cookie died mid-run
            post["status"] = "no_access"
            log.warning("No access to post %s (higher tier?), skipping", post_id)
        else:
            post["status"] = "failed"
            post["attempts"] = post.get("attempts", 0) + 1
            post["error"] = message[-500:]
            log.error("Post %s failed: %s", post_id, message)
        self.state.save()

    # ---- downloading -------------------------------------------------------

    def download(self, info: dict) -> list[Path]:
        ep = self.plan(info)
        show_dir = self.library_dir / ep.show_folder
        season_dir = show_dir / ep.season_dir
        season_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_show_assets(show_dir, ep)

        entries = list(info["entries"]) if info.get("_type") == "playlist" else [info]
        files: list[Path] = []
        for i, entry in enumerate(entries, start=1):
            basename = ep.basename(part=i if len(entries) > 1 else None)
            if (season_dir / f"{basename}.mp4").exists():
                basename += f" ({ep.post_id})"
            entry.update(
                title=ep.title or basename,
                description=ep.description,
                show=ep.show_folder,
                series=ep.show_folder,
                season_number=ep.season,
                episode_number=ep.episode,
                artist=self.creator_name,
            )
            params = self._params(
                paths={"home": str(season_dir), "temp": str(self.tmp_dir)},
                outtmpl={"default": f"{basename}.%(ext)s"},
                format="bv*+ba/b",
                merge_output_format="mp4",
                writethumbnail=True,
                postprocessors=[
                    {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
                    {"key": "FFmpegMetadata", "add_metadata": True},
                    {"key": "EmbedThumbnail", "already_have_thumbnail": True},
                ],
            )
            with YoutubeDL(params) as ydl:
                result = ydl.process_ie_result(entry, download=True)
            path = Path(result["requested_downloads"][0]["filepath"])
            write_episode_nfo(path.with_suffix(".nfo"), ep)
            files.append(path)
        return files

    def _ensure_show_assets(self, show_dir: Path, ep: Episode) -> None:
        if ep.source_show:
            plot = f"{self.creator_name} reacts to {ep.source_show}."
        else:
            plot = f"Other videos from {self.creator_name} on Patreon."
        write_show_nfo(show_dir / "tvshow.nfo", ep.show_folder, plot)
        poster = show_dir / "poster.jpg"
        if self.creator_avatar and not poster.exists():
            try:
                with YoutubeDL(self._params()) as ydl:
                    poster.write_bytes(ydl.urlopen(self.creator_avatar).read())
            except Exception as e:  # cosmetic, never fail a download over it
                log.warning("Could not fetch poster: %s", e)

    # ---- orchestration -----------------------------------------------------

    def run(self) -> RunResult:
        self.refresh_cookies()
        user = self.check_login()
        log.info("Logged in to Patreon as %s", user)
        result = RunResult()
        candidates = self.collect()
        max_dl = self.creator.max_downloads_per_run
        if max_dl and len(candidates) > max_dl:
            result.pending = len(candidates) - max_dl
            candidates = candidates[:max_dl]
        log.info("%s: %d new post(s) to download", self.creator_name, len(candidates))
        for info in candidates:
            post_id = str(info["id"])
            log.info("Downloading %s: %s", post_id, info.get("title"))
            try:
                files = self.download(info)
            except DownloadError as e:
                self._record_error(post_id, str(e))
                result.failed.append(post_id)
                continue
            post = self.state.posts.setdefault(post_id, {})
            post.update(status="done", title=info.get("title"), files=[str(f) for f in files])
            post.pop("error", None)
            self.state.save()
            result.downloaded.append(post_id)
            log.info("Saved %s", ", ".join(f.name for f in files))
        self.state.save()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        return result


def _post_id(entry: dict) -> str:
    """Flat campaign entries may only carry the post URL, which ends in the numeric post id."""
    if entry.get("id"):
        return str(entry["id"])
    match = re.search(r"(\d+)/?$", entry["url"])
    if not match:
        raise ValueError(f"Cannot find post id in {entry['url']}")
    return match.group(1)


def refresh_plex(cfg: Config) -> None:
    plex = cfg.plex
    if not plex:
        return
    url = f"{plex.url.rstrip('/')}/library/sections/{plex.section_id}/refresh?X-Plex-Token={plex.token}"
    try:
        urllib.request.urlopen(url, timeout=30).read()
        log.info("Triggered Plex library scan")
    except Exception as e:
        log.warning("Plex refresh failed: %s", e)


def heartbeat(url: str | None, ok: bool, msg: str) -> None:
    """Uptime Kuma push-style heartbeat: ?status=up|down&msg=..."""
    if not url:
        return
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}{urllib.parse.urlencode({'status': 'up' if ok else 'down', 'msg': msg[:200]})}"
    try:
        urllib.request.urlopen(full, timeout=15).read()
    except Exception as e:
        log.warning("Heartbeat failed: %s", e)
