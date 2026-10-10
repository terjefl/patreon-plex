# patreon-plex

Download the Patreon videos you have access to and file them as a Plex-friendly TV library.

> You need to be a paying patron with access to the posts. This tool only downloads what your own account can already watch on patreon.com, for personal viewing.

Several creators can be followed with one Patreon login. Each gets a folder under the library. Posts with `SxE` in the title, like `Taskmaster - S21 E1 - Cube Is Good`, become proper episodes of their own show:

```
Mandy Cane Lane/
└── Mandy Cane Lane - Taskmaster/
    ├── tvshow.nfo
    ├── poster.jpg
    └── Season 21/
        ├── Mandy Cane Lane - Taskmaster - S21E01 - Cube Is Good.mp4
        ├── Mandy Cane Lane - Taskmaster - S21E01 - Cube Is Good.jpg
        └── Mandy Cane Lane - Taskmaster - S21E01 - Cube Is Good.nfo
```

- `Show - something` without `SxE`, where `Show` is already known, goes to that show's **Season 00** (specials). List official special numbers under `specials` in the config (for example from TheTVDB) and matching posts get those numbers and titles; the rest are numbered around them.
- Everything else goes to a show named after the creator, with one season per year, numbered in publishing order.
- Each show gets a generated poster with its name on a frame from one of its episodes, so shows from the same creator are easy to tell apart. In Plex, shows are titled by the source show alone (`show_title_template`).
- Title, description, date, season/episode and thumbnail are embedded in the MP4 and also written as `.nfo` and `.jpg` sidecars (read by Jellyfin, Infuse and Kodi).

Videos are downloaded as-is from Patreon (typically 1080p H.264/AAC), so Plex can direct-play them.

## Setup

1. **Cookies:** log in to patreon.com in a browser, export cookies for `patreon.com` in Netscape format (for example with the *Get cookies.txt LOCALLY* extension) and save the file as `config/cookies.txt`.
   The session lasts several months, but logging out of that browser session kills it. Use a private window and close it without logging out.
2. **Config:** copy `config.template.yaml` to `config/config.yaml` and add one entry under `creators` per creator.
3. **Run:** use `compose.example.yml`. The container checks for new posts every `interval_minutes`.

Commands (`docker exec patreon-plex patreon-plex --config /config/config.yaml <command>`):

| Command | What it does |
|---|---|
| `check` | Verify the cookie |
| `plan -n 20 [--creator SLUG]` | Show how the latest 20 posts would be named, without downloading anything |
| `refresh-art` | Rewrite show titles, posters and backgrounds (after changing `show_title_template`) |
| `likes [--all] [--mark-watched]` | Refresh which posts you have liked on Patreon; optionally mark liked episodes as watched in Plex |
| `run` | Download new posts once |
| `loop` | Default: `run` every `interval_minutes` |

## Plex

Create a **TV Shows** library and add each creator's folder (for example `Patreon/Mandy Cane Lane`) as a folder in it. Plex expects the show folders directly under each library folder. Choose the **Plex NFO Series** agent with the **Plex TV Series** scanner. It reads the `.nfo` sidecars, so titles, descriptions, dates, posters and episode thumbnails all show up, and Plex doesn't try to match the folders against real TV shows.

With several creators, give each one its own library if you like: set `plex_section_id` on the creator to that library's id, and `plex.section_id` stays the default for the others. Scans, watched status, likes and the index page then use each creator's own library.

A creator's library can also hold their videos from elsewhere, for example YouTube downloads from [Pinchflat](https://github.com/kieraneglin/pinchflat) as a show of its own. Add that folder to the same library and keep it outside `library_dir`: patreon-plex only looks at, cleans up and lists files under `library_dir` that it downloaded itself. For Pinchflat, a media profile with NFO files and the template `/TV/{{ source_custom_name }}/{{ source_custom_name }}/{{ season_by_year__episode_by_date_and_index }} - {{ title }} [{{ id }}].{{ ext }}` gives one show per channel with a season per year; add `…/TV/<source name>` as the library folder.

## Throttling

`rate_limit` caps the download speed and `pause_seconds` adds a random pause between videos, and `max_downloads_per_run` spreads a large backlog over several hourly runs. Downloads are otherwise far faster than real-time playback (an hour of video in about two minutes), which is an unusual pattern for one account.

## Index page

With a `plex` section, the container serves an index page on `web_port` (default 8000): every downloaded episode grouped by show, with links to the Patreon post and the Plex episode, whether you have watched it in Plex, and whether you have liked it on Patreon. "Watched, not liked" is listed at the top, so you can like what you have seen.

The page has no login of its own; put it behind an authenticating proxy (for example Cloudflare Access).

Downloads never play through Patreon's player, so the creator's statistics never show you watching; a like is the signal she does get. Liking can't be automated: Patreon rejects like requests without the web app's CSRF token. Like status is read-only: each run checks every watched-but-not-liked post, plus 20 others not checked in the last week. The page's button re-checks the watched ones on demand. `likes --all` checks every downloaded post at once.

A like means you have seen the episode, often before it was downloaded, so liked episodes are marked as watched in Plex after each run (`likes --all --mark-watched` does it now). Each episode is marked once, so setting one back to unwatched in Plex sticks.

## Monitoring

When the cookie expires, every run fails with `Patreon login expired`. Set `heartbeat_url` to an Uptime Kuma push monitor to be alerted. Export a new `cookies.txt`; the next run picks it up without a restart.

## State

`data/<creator>/state.json` records which posts are handled: `done`, `no_media` (text or poll posts), `no_access` (not visible to your tier, e.g. a post only for free members) or `failed` (retried up to 5 times). Delete a post's entry to download it again.
