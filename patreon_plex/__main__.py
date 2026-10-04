import argparse
import logging
import time
from pathlib import Path

from .config import Config, load_config
from .harvest import Harvester, LoginExpired, heartbeat, refresh_plex
from .likes import LikeRejected, like, like_watched

log = logging.getLogger("patreon_plex")


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
            log.exception("Run for %s failed", creator.creator)
            errors.append(f"{creator.creator}: {e}")
            continue
        downloaded += len(result.downloaded)
        failed += len(result.failed)
        pending += result.pending
        if cfg.like_watched and cfg.plex:
            try:
                like_watched(harvester)
            except LikeRejected as e:
                log.error("Liking stopped: %s", e)
                errors.append(f"likes: {e}")
            except Exception as e:  # likes are a nicety; never fail the run over them
                log.warning("Liking watched posts failed: %s", e)
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
    parser = argparse.ArgumentParser(prog="patreon-plex", description="Download Patreon videos into a Plex TV library")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify the Patreon cookie")
    p_plan = sub.add_parser("plan", help="show how the latest posts would be named (no downloads)")
    p_plan.add_argument("-n", type=int, default=20)
    p_plan.add_argument("--creator", help="only this creator (slug)")
    sub.add_parser("refresh-art", help="rewrite show titles, posters and backgrounds")
    p_likes = sub.add_parser("likes", help="like posts whose episodes are watched in Plex")
    p_likes.add_argument("--dry-run", action="store_true", help="only show what would be liked")
    p_like = sub.add_parser("like", help="like one post (to test that liking works)")
    p_like.add_argument("post_id")
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
    elif args.command == "likes":
        if not cfg.plex:
            raise SystemExit("likes needs a `plex` section with url, token and section_id")
        for creator in cfg.creators:
            h = Harvester(cfg, creator, dry_run=args.dry_run)
            h.refresh_cookies()
            print(f"{creator.creator}: liked {len(like_watched(h, dry_run=args.dry_run))}")
    elif args.command == "like":
        h = Harvester(cfg, cfg.creators[0], dry_run=True)
        h.refresh_cookies()
        from yt_dlp import YoutubeDL

        with YoutubeDL(h._params()) as ydl:
            try:
                like(ydl, args.post_id)
            except LikeRejected as e:
                raise SystemExit(f"Rejected: {e}")
        print(f"Liked {args.post_id}")
    elif args.command == "run":
        raise SystemExit(0 if run_once(cfg) else 1)
    elif args.command == "loop":
        while True:
            run_once(cfg)
            log.info("Sleeping %d minutes", cfg.interval_minutes)
            time.sleep(cfg.interval_minutes * 60)


if __name__ == "__main__":
    main()
