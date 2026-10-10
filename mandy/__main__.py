import argparse
import logging
import time
from pathlib import Path

from yt_dlp.networking.exceptions import TransportError

from .config import Config, load_config
from .harvest import Harvester, LoginExpired, heartbeat, refresh_plex
from .likes import check_likes, mark_liked_watched
from .stats import refresh_youtube, youtube_due

log = logging.getLogger("mandy")


def _is_network_error(e: BaseException | None) -> bool:
    """A dropped connection or timeout: the next run will likely work, so a traceback is just noise."""
    while e is not None:
        if isinstance(e, (TransportError, ConnectionError, TimeoutError)):
            return True
        e = getattr(e, "cause", None) or e.__cause__
    return False


def run_once(cfg: Config) -> bool:
    downloaded = failed = pending = 0
    errors: list[str] = []
    for creator in cfg.creators:
        harvester = Harvester(cfg, creator)
        try:
            result = harvester.run()
        except LoginExpired as e:
            # One account for all creators, so there's no point trying the rest.
            log.error("Patreon login expired, export a new cookies.txt: %s", e)
            heartbeat(cfg.heartbeat_url, False, "Patreon cookie expired - export a new cookies.txt")
            return False
        except Exception as e:
            if _is_network_error(e):
                log.warning("Run for %s failed: %s", creator.creator, e)
            else:
                log.exception("Run for %s failed", creator.creator)
            errors.append(f"{creator.creator}: {e}")
            continue
        downloaded += len(result.downloaded)
        failed += len(result.failed)
        pending += result.pending
        if cfg.plex:
            try:
                check_likes(cfg, creator)
                mark_liked_watched(cfg, creator)
            except Exception as e:  # like status is a nicety; never fail the run over it
                log.warning("Checking like status failed: %s", e)
    if downloaded:
        refresh_plex(cfg)
    msg = f"{downloaded} downloaded, {failed} failed, {pending} pending"
    if errors:
        msg += " | " + "; ".join(errors)
    log.info(msg)
    ok = not failed and not errors
    heartbeat(cfg.heartbeat_url, ok, msg)
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(prog="mandy", description="Mandy Cane Lane's Patreon videos in a Plex TV library")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify the Patreon cookie")
    p_plan = sub.add_parser("plan", help="show how the latest posts would be named (no downloads)")
    p_plan.add_argument("-n", type=int, default=20)
    p_plan.add_argument("--creator", help="only this creator (slug)")
    sub.add_parser("refresh-art", help="rewrite show titles, posters and backgrounds")
    p_plots = sub.add_parser("refresh-plots", help="fill empty episode descriptions from the posts, clean the rest")
    p_plots.add_argument(
        "--remove-orphans", action="store_true", help="also delete .nfo/.jpg left without a video by failed downloads"
    )
    p_likes = sub.add_parser("likes", help="refresh which posts you have liked on Patreon")
    p_likes.add_argument("--all", action="store_true", help="check every downloaded post now")
    p_likes.add_argument("--mark-watched", action="store_true", help="then mark liked episodes as watched in Plex")
    p_refile = sub.add_parser("refile", help="move downloaded posts to where their title puts them now")
    p_refile.add_argument("post_ids", nargs="+")
    p_yt = sub.add_parser("youtube-stats", help="look up the creators' YouTube videos for the statistics page")
    p_yt.add_argument("--all", action="store_true", help="look up every new video now, not 300 at a time")
    sub.add_parser("run", help="download new posts once")
    sub.add_parser("loop", help="download new posts every interval_minutes")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)

    if args.command == "check":
        h = Harvester(cfg, cfg.creators[0], dry_run=True)
        h.refresh_cookies()
        try:
            print(f"OK, logged in as {h.check_login()}")
        except LoginExpired as e:
            raise SystemExit(f"Login expired: {e}")
    elif args.command == "plan":
        creators = [cfg.find_creator(args.creator)] if args.creator else cfg.creators
        for creator in creators:
            h = Harvester(cfg, creator, dry_run=True)
            h.refresh_cookies()
            for info in h.collect(limit=args.n):
                ep = h.plan(info)
                path = h.library_dir / ep.show_folder / ep.season_dir / f"{ep.basename()}.mp4"
                print(f"{info['title']!r}\n    -> {path.relative_to(cfg.library_dir)}")
    elif args.command == "refresh-art":
        for creator in cfg.creators:
            print(f"{creator.creator}: {Harvester(cfg, creator).refresh_show_art()} show(s) refreshed")
    elif args.command == "refresh-plots":
        for creator in cfg.creators:
            harvester = Harvester(cfg, creator)
            if args.remove_orphans:
                print(f"{creator.creator}: {len(harvester.remove_orphans())} leftover file(s) removed")
            print(f"{creator.creator}: {harvester.refresh_plots()} description(s) updated")
    elif args.command == "likes":
        if not cfg.plex:
            raise SystemExit("likes needs a `plex` section with url, token and section_id")
        for creator in cfg.creators:
            print(f"{creator.creator}: checked {check_likes(cfg, creator, all_posts=args.all)} post(s)")
            if args.mark_watched:
                print(f"{creator.creator}: marked {mark_liked_watched(cfg, creator)} episode(s) as watched")
    elif args.command == "refile":
        harvester = Harvester(cfg, cfg.creators[0])
        moved = [m for post_id in args.post_ids for m in harvester.refile(post_id)]
        for old, new in moved:
            print(f"{old.relative_to(harvester.library_dir)}\n  -> {new.relative_to(harvester.library_dir)}")
        if moved:
            refresh_plex(cfg)
        print(f"{len(moved)} file(s) moved")
    elif args.command == "youtube-stats":
        for creator in cfg.creators:
            if creator.youtube_url:
                left = refresh_youtube(cfg, creator, max_new=None if args.all else 300)
                print(f"{creator.creator}: YouTube list updated, {left} video(s) left to look up")
    elif args.command == "run":
        raise SystemExit(0 if run_once(cfg) else 1)
    elif args.command == "loop":
        if cfg.web_port and cfg.plex:
            from .web import serve

            serve(cfg, cfg.web_port)
        while True:
            run_once(cfg)
            for creator in cfg.creators:
                if youtube_due(cfg, creator):
                    try:
                        refresh_youtube(cfg, creator)
                    except Exception as e:  # statistics are a nicety; never stop the loop over them
                        log.warning("Updating YouTube statistics for %s failed: %s", creator.creator, e)
            log.info("Sleeping %d minutes", cfg.interval_minutes)
            time.sleep(cfg.interval_minutes * 60)


if __name__ == "__main__":
    main()
