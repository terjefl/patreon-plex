import argparse
import logging
import time
from pathlib import Path

from .config import load_config
from .harvest import Harvester, LoginExpired, heartbeat

log = logging.getLogger("patreon_plex")


def run_once(cfg) -> bool:
    try:
        result = Harvester(cfg).run()
    except LoginExpired as e:
        log.error("Patreon login expired, export a new cookies.txt: %s", e)
        heartbeat(cfg.heartbeat_url, False, "Patreon cookie expired - export a new cookies.txt")
        return False
    except Exception as e:
        log.exception("Run failed")
        heartbeat(cfg.heartbeat_url, False, f"Run failed: {e}")
        return False
    msg = f"{len(result.downloaded)} downloaded, {len(result.failed)} failed, {result.pending} pending"
    log.info(msg)
    heartbeat(cfg.heartbeat_url, not result.failed, msg)
    return not result.failed


def main() -> None:
    parser = argparse.ArgumentParser(prog="patreon-plex", description="Download Patreon videos into a Plex TV library")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify the Patreon cookie")
    p_plan = sub.add_parser("plan", help="show how the latest posts would be named (no downloads)")
    p_plan.add_argument("-n", type=int, default=20)
    sub.add_parser("run", help="download new posts once")
    sub.add_parser("loop", help="download new posts every interval_minutes")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)

    if args.command == "check":
        h = Harvester(cfg, dry_run=True)
        h.refresh_cookies()
        try:
            print(f"OK, logged in as {h.check_login()}")
        except LoginExpired as e:
            raise SystemExit(f"Login expired: {e}")
    elif args.command == "plan":
        h = Harvester(cfg, dry_run=True)
        h.refresh_cookies()
        for info in h.collect(limit=args.n):
            ep = h.plan(info)
            print(f"{info['title']!r}\n    -> {ep.show_folder}/{ep.season_dir}/{ep.basename()}.mp4")
    elif args.command == "run":
        raise SystemExit(0 if run_once(cfg) else 1)
    elif args.command == "loop":
        while True:
            run_once(cfg)
            log.info("Sleeping %d minutes", cfg.interval_minutes)
            time.sleep(cfg.interval_minutes * 60)


if __name__ == "__main__":
    main()
