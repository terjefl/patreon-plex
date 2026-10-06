import io
import json
import random
import logging
import re
import shutil
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError, RequestError
from yt_dlp.utils import DownloadError, parse_bytes

from .config import Config, CreatorConfig
from .library import Episode, write_episode_nfo, write_show_nfo
from .poster import make_poster
from .state import State
from .titles import clean, parse_title, safe_filename, show_key

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
# Without `since`: stop paging the (newest-first) post list after this many handled posts in a row.
STOP_AFTER_KNOWN = 25
# ...or this many posts in a row older than `since`.
STOP_AFTER_OLD = 5
# Hosts whose links in a post's text are taken as the post's video, when it has no embed.
VIDEO_LINK_RE = re.compile(
    r"https?://(?:www\.)?(?:drive\.google\.com/(?:file/d/|open\?id=)|dai\.ly/|dailymotion\.com/video/"
    r"|youtu\.be/|youtube\.com/watch|vimeo\.com/\d)\S*",
    re.IGNORECASE,
)
# A host telling us to slow down: rate limited, or Google Drive's per-file download quota.
THROTTLED_RE = re.compile(r"HTTP Error 429|Too Many Requests|Too many users have viewed or downloaded", re.IGNORECASE)
# Throttled posts wait this long before the next try, doubling each time up to a day. They
# don't use up attempts: the file is fine, the host just wants us to come back later.
THROTTLE_WAIT = 30 * 60
THROTTLE_WAIT_MAX = 24 * 3600


class _YtdlpLogger:
    """yt-dlp's messages, minus the "no media" error the harvester handles and reports itself.

    Remembers whether the host throttled us: Google Drive's quota only shows as a warning,
    after which yt-dlp downloads the error page and fails on it with "Invalid data".
    """

    def __init__(self):
        self.throttled = False

    def debug(self, msg: str) -> None:
        log.debug(msg)

    def info(self, msg: str) -> None:
        log.info(msg)

    def warning(self, msg: str) -> None:
        self.throttled |= bool(THROTTLED_RE.search(msg))
        log.warning(msg)

    def error(self, msg: str) -> None:
        self.throttled |= bool(THROTTLED_RE.search(msg))
        (log.debug if "No supported media" in msg else log.error)(msg)


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
        self.ytdlp_logger = _YtdlpLogger()

    def _params(self, **extra) -> dict:
        return {
            "cookiefile": str(self.cookies),
            "quiet": True,
            "noprogress": True,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": 4,
            "logger": self.ytdlp_logger,
            # Back off between yt-dlp's own retries instead of hammering a host that said no
            "retry_sleep_functions": {"http": _backoff, "fragment": _backoff},
            "ratelimit": parse_bytes(self.cfg.rate_limit) if self.cfg.rate_limit else None,
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

        def numbered(counter: str, reserved: set[int] = frozenset()) -> int:
            # Assigned once per post and remembered, so retries keep the same number.
            if "number" not in post_state:
                post_state["number"] = self.state.next_number(counter, reserved)
            return post_state["number"]

        parsed = parse_title(title)
        special_show = self._known_show_prefix(title)
        if parsed:
            show = self._canonical_show(parsed.show)
            season, episode, ep_title = parsed.season, parsed.episode, parsed.episode_title
        elif special_show:
            # "Only Fools And Horses - Dates (1988)": a known show without SxE goes to Specials.
            show = special_show
            season, ep_title = 0, clean(title.split(" - ", 1)[1])
            table = self._specials_for(show)
            official = _match_special(table, ep_title)
            if official:
                ep_title, episode = official
            else:
                episode = numbered(f"special:{show_key(show)}", set(table.values()))
        else:
            # Everything else: one season per year, numbered in publishing order.
            show = None
            season, episode, ep_title = published.year, numbered(f"misc:{published.year}"), title

        if show:
            folder = self.creator.show_name_template.format(creator=self.creator_name, show=show)
            show_title = self.creator.show_title_template.format(creator=self.creator_name, show=show)
        else:
            folder = show_title = self.creator.misc_show_name.format(creator=self.creator_name)
        return Episode(
            post_id=post_id,
            show_folder=safe_filename(folder),
            show_title=show_title,
            source_show=show,
            season=season,
            episode=episode,
            title=ep_title,
            description=description,
            published=published,
            url=info.get("webpage_url") or "",
        )

    def _specials_for(self, show: str) -> dict[str, int]:
        for name, table in self.creator.specials.items():
            if show_key(name) == show_key(show):
                return table
        return {}

    def _known_show_prefix(self, title: str) -> str | None:
        if " - " not in title:
            return None
        key = show_key(title.split(" - ", 1)[0])
        aliases = {show_key(k): v for k, v in self.creator.show_aliases.items()}
        return aliases.get(key) or self.state.shows.get(key)

    # ---- listing -----------------------------------------------------------

    def collect(self, limit: int | None = None) -> list[dict]:
        """Return unhandled posts, oldest first.

        Normally these are stubs ({id, title, timestamp}) from the state cache: a post is
        only looked up on Patreon the first time it is seen, so a backlog spread over many
        runs doesn't re-query hundreds of posts every hour. Call `extract()` before
        downloading one. With `limit` (the plan command) they are full info dicts.
        """
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
                    # With `since`, keep paging until posts get too old: the date may have been
                    # moved back, leaving unhandled posts behind a long run of handled ones.
                    if not self.creator.since and known_streak >= STOP_AFTER_KNOWN:
                        break
                    continue
                known_streak = 0
                cached = self.state.posts.get(post_id, {})
                if limit is None and cached.get("retry_after", 0) > time.time():
                    continue
                # A post marked no_media before its text was searched for links gets a fresh look.
                if limit is None and "published" in cached and cached.get("status") != "no_media":
                    info = {"id": post_id, "title": cached.get("title"), "timestamp": cached["published"], "stub": True}
                else:
                    try:
                        info = self._extract_post(ydl, post_id)
                    except DownloadError as e:
                        self._record_error(post_id, str(e))
                        continue
                    if limit is None:
                        post = self.state.posts.setdefault(post_id, {"status": "pending"})
                        post.update(published=info["timestamp"], title=info.get("title"))
                        if post["status"] == "no_media":
                            post["status"] = "pending"
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
        self.state.save()
        # Register every show seen in this batch up front, so "Show - Special" posted
        # before the show's first SxE episode still lands in that show's Season 00.
        for info in candidates:
            parsed = parse_title(clean(info.get("title") or ""))
            if parsed:
                self._canonical_show(parsed.show)
        return list(reversed(candidates))

    def extract(self, info: dict) -> dict:
        """Full info for a post (a no-op unless `info` is a cached stub)."""
        if not info.get("stub"):
            return info
        with YoutubeDL(self._params()) as ydl:
            return self._extract_post(ydl, str(info["id"]))

    def _extract_post(self, ydl: YoutubeDL, post_id: str) -> dict:
        try:
            return ydl.extract_info(f"https://www.patreon.com/posts/{post_id}", download=False, process=False)
        except DownloadError as e:
            if "No supported media" not in str(e):
                raise
            # yt-dlp only sees embeds and attached files, and reads the post text from a field
            # Patreon no longer fills. Many posts are an image with the video linked in the text.
            try:
                info = self._linked_post(ydl, post_id)
            except (RequestError, KeyError, ValueError) as lookup_error:
                # Not "no media": count it as a failed attempt, so the next run tries again.
                raise DownloadError(f"Could not look for video links in the post: {lookup_error}") from e
            if not info:
                raise
            return info

    def _linked_post(self, ydl: YoutubeDL, post_id: str) -> dict | None:
        """A playlist of the video links (Google Drive, Dailymotion, ...) in a post's text, if any."""
        fields = "title,content_json_string,published_at,url,image"
        resp = ydl.urlopen(Request(f"https://www.patreon.com/api/posts/{post_id}?fields[post]={fields}"))
        attrs = json.loads(resp.read())["data"]["attributes"]
        urls = linked_videos(attrs.get("content_json_string"))
        if not urls:
            return None
        log.info("Post %s links its video: %s", post_id, ", ".join(urls))
        return {
            "_type": "playlist",
            "id": post_id,
            "title": attrs.get("title"),
            "timestamp": int(datetime.fromisoformat(attrs["published_at"]).timestamp()),
            "webpage_url": attrs.get("url"),
            "thumbnail": (attrs.get("image") or {}).get("large_url"),
            # url_transparent: the episode title and numbers set in download() win over the host's
            "entries": [{"_type": "url_transparent", "url": url} for url in urls],
        }

    def _record_error(self, post_id: str, message: str, throttled: bool = False) -> None:
        post = self.state.posts.setdefault(post_id, {"status": "pending"})
        if throttled or THROTTLED_RE.search(message):
            post["status"] = "failed"
            post["throttled"] = post.get("throttled", 0) + 1
            wait = min(THROTTLE_WAIT * 2 ** (post["throttled"] - 1), THROTTLE_WAIT_MAX)
            post["retry_after"] = int(time.time() + wait)
            post["error"] = message[-500:]
            log.warning(
                "Post %s: the host is throttling us, trying again after %s",
                post_id,
                datetime.fromtimestamp(post["retry_after"]).strftime("%d.%m %H:%M"),
            )
        elif "No supported media" in message:
            post["status"] = "no_media"
            post["links_checked"] = True
            log.info("Post %s has no video, skipping", post_id)
        elif "do not have access" in message:
            self.check_login()  # raises LoginExpired if the cookie died mid-run
            post["status"] = "no_access"
            log.warning("Post %s is not visible to you (e.g. only for free members), skipping", post_id)
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
        # Plex scans the moment the video lands, and its NFO agent identifies the show by the
        # metadata it finds then. So every sidecar must exist before the video does.
        preview = self._fetch_thumbnail(info)
        self._ensure_show_assets(show_dir, ep.show_title, ep.source_show, preview)

        entries = list(info["entries"]) if info.get("_type") == "playlist" else [info]
        files: list[Path] = []
        for i, entry in enumerate(entries, start=1):
            basename = ep.basename(part=i if len(entries) > 1 else None)
            if (season_dir / f"{basename}.mp4").exists():
                basename += f" ({ep.post_id})"
            nfo = season_dir / f"{basename}.nfo"
            write_episode_nfo(nfo, ep)
            entry.update(
                title=ep.display_title,
                description=ep.description,
                show=ep.show_title,
                series=ep.show_title,
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
            if path.with_suffix(".nfo") != nfo:
                nfo.replace(path.with_suffix(".nfo"))
            files.append(path)
        if preview:
            preview.unlink(missing_ok=True)
        return files

    def _fetch_thumbnail(self, info: dict) -> Path | None:
        """The post's thumbnail as a local JPEG, for show artwork made before the download."""
        url = info.get("thumbnail")
        if not url:
            return None
        try:
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
            out = self.tmp_dir / f"preview-{info['id']}.jpg"
            with YoutubeDL(self._params()) as ydl:
                data = ydl.urlopen(url).read()
            Image.open(io.BytesIO(data)).convert("RGB").save(out, "JPEG", quality=92)
            return out
        except Exception as e:
            log.warning("Could not fetch thumbnail for %s: %s", info.get("id"), e)
            return None

    def _ensure_show_assets(
        self, show_dir: Path, title: str, source_show: str | None, thumb: Path | None, force: bool = False
    ) -> None:
        """tvshow.nfo, plus a poster and background that tell the shows apart. Cosmetic: never fails."""
        try:
            if source_show:
                plot = f"{self.creator_name} reacts to {source_show}."
            else:
                plot = f"Other videos from {self.creator_name} on Patreon."
            write_show_nfo(show_dir / "tvshow.nfo", title, plot)
            has_thumb = thumb is not None and thumb.exists()
            poster = show_dir / "poster.jpg"
            if force or not poster.exists():
                if source_show and has_thumb:
                    make_poster(thumb, title, self.creator_name, poster)
                elif self.creator_avatar and not poster.exists():
                    with YoutubeDL(self._params()) as ydl:
                        poster.write_bytes(ydl.urlopen(self.creator_avatar).read())
            fanart = show_dir / "fanart.jpg"
            if has_thumb and (force or not fanart.exists()):
                shutil.copyfile(thumb, fanart)
        except Exception as e:
            log.warning("Could not update artwork for %s: %s", show_dir.name, e)

    def _pause(self) -> None:
        low, high = self.cfg.pause_seconds
        if high > 0:
            seconds = random.uniform(low, high)
            log.info("Pausing %.0f s before next download", seconds)
            time.sleep(seconds)

    def refresh_show_art(self) -> int:
        """Rewrite tvshow.nfo, poster and background for every show folder in the library."""
        if not self.library_dir.exists():
            return 0
        fmt = {"creator": self.creator_name}
        by_folder: dict[str, tuple[str, str | None]] = {
            safe_filename(self.creator.misc_show_name.format(**fmt)): (self.creator.misc_show_name.format(**fmt), None)
        }
        for show in {*self.state.shows.values(), *self.creator.show_aliases.values()}:
            folder = safe_filename(self.creator.show_name_template.format(show=show, **fmt))
            by_folder[folder] = (self.creator.show_title_template.format(show=show, **fmt), show)
        count = 0
        for show_dir in sorted(p for p in self.library_dir.iterdir() if p.is_dir()):
            if show_dir.name not in by_folder:
                log.warning("Unknown show folder %s, skipping", show_dir.name)
                continue
            title, source_show = by_folder[show_dir.name]
            thumbs = sorted(show_dir.glob("*/*.jpg"), key=lambda p: p.stat().st_mtime)
            self._ensure_show_assets(show_dir, title, source_show, thumbs[-1] if thumbs else None, force=True)
            log.info("Refreshed artwork for %s (%s)", show_dir.name, title)
            count += 1
        return count

    # ---- orchestration -----------------------------------------------------

    def run(self) -> RunResult:
        # A run that was interrupted (container restart, crash) never reached the cleanup
        # at the end, so start from an empty tmp dir. The cost is that a half-finished
        # download starts over instead of resuming.
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
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
        throttled_hosts: set[str] = set()
        for i, info in enumerate(candidates):
            if i:
                self._pause()
            post_id = str(info["id"])
            post_title = info.get("title")  # download() rewrites info["title"] to the episode title
            hosts: set[str] = set()
            self.ytdlp_logger.throttled = False
            try:
                info = self.extract(info)
                hosts = _linked_hosts(info)
                if hosts & throttled_hosts:
                    # Asking again while throttled only makes it worse; wait for the next run.
                    log.info("Skipping %s for now: %s is throttling us", post_id, ", ".join(hosts & throttled_hosts))
                    result.pending += 1
                    continue
                log.info("Downloading %s: %s", post_id, post_title)
                files = self.download(info)
            except DownloadError as e:
                throttled = self.ytdlp_logger.throttled or bool(THROTTLED_RE.search(str(e)))
                self._record_error(post_id, str(e), throttled=throttled)
                if throttled:
                    throttled_hosts |= hosts
                    result.pending += 1
                else:
                    result.failed.append(post_id)
                continue
            post = self.state.posts.setdefault(post_id, {})
            post.update(status="done", title=post_title, files=[str(f) for f in files])
            for key in ("error", "retry_after", "throttled"):
                post.pop(key, None)
            self.state.save()
            result.downloaded.append(post_id)
            log.info("Saved %s", ", ".join(f.name for f in files))
        self.state.save()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        return result


def _backoff(n: int) -> float:
    """Seconds before yt-dlp's retry number n: 2, 4, 8 ... up to two minutes."""
    return min(2.0 ** (n + 1), 120.0)


def _linked_hosts(info: dict) -> set[str]:
    """Hosts of a post's videos that live elsewhere: linked in the text, or embedded (e.g. a
    Google Drive embed comes back as a url_transparent result). Empty for videos on Patreon."""
    items = [e for e in info.get("entries") or [] if isinstance(e, dict)] or [info]
    urls = [e.get("url", "") for e in items if e.get("_type") in ("url", "url_transparent")]
    return {_host(u) for u in urls if u}


def _host(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    return {"dai.ly": "dailymotion.com", "youtu.be": "youtube.com"}.get(host, host)


def _special_key(title: str) -> str:
    """'The Jolly Boys' Outing (Special)' and 'the jolly boys outing' compare equal."""
    title = re.sub(r"\([^)]*\)", " ", title)
    title = re.sub(r"\b(christmas\s+)?special\b", " ", title, flags=re.IGNORECASE)
    return show_key(title)


def _match_special(table: dict[str, int], title: str) -> tuple[str, int] | None:
    """Official (title, number) for a special, from the configured `specials` table."""
    key = _special_key(title)
    for name, number in table.items():
        if _special_key(name) == key:
            return name, number
    return None


def linked_videos(content_json: str | None) -> list[str]:
    """Video links in a post's text (Patreon's rich-text JSON), in order, without duplicates."""
    if not content_json:
        return []
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            # A link's shown text may be shortened, so its href wins; bare URLs count too.
            hrefs = [(m.get("attrs") or {}).get("href") for m in node.get("marks") or []]
            hrefs = [h for h in hrefs if h]
            if hrefs:
                found.extend(hrefs)
            elif node.get("type") == "text":
                found.append(node.get("text") or "")
            for child in node.get("content") or []:
                walk(child)

    walk(json.loads(content_json))
    urls: dict[str, str] = {}
    for text in found:
        for m in VIDEO_LINK_RE.finditer(text):
            url = m.group(0).rstrip(".,)")
            urls.setdefault(_link_key(url), url)
    return list(urls.values())


def _link_key(url: str) -> str:
    """The same video, whether linked as ".../view?usp=sharing", ".../view" or "open?id=..."."""
    drive = re.search(r"drive\.google\.com/(?:file/d/|open\?id=)([\w-]+)", url)
    if drive:
        return "drive:" + drive.group(1)
    if "youtube.com/watch" in url:
        return url
    return re.sub(r"^https?://(?:www\.)?|[?#].*$", "", url).rstrip("/")


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
