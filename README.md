# Mandy

Everything [Mandy Cane Lane](https://www.patreon.com/c/MandyCaneLane) posts, in one Plex library: her Patreon videos, downloaded by this tool, next to her YouTube channel, downloaded by [Pinchflat](https://github.com/kieraneglin/pinchflat). On top of that, an index page with every video, what you have watched and liked, and a statistics page that can be shared with her.

> You need to be a paying patron with access to the posts. This tool only downloads what your own account can already watch on patreon.com, for personal viewing.

## Patreon videos

Posts with `SxE` in the title, like `Taskmaster - S21 E1 - Cube Is Good`, become proper episodes of their own show:

```
Mandy/
└── Mandy Cane Lane - Taskmaster/
    ├── tvshow.nfo
    ├── poster.jpg
    └── Season 21/
        ├── Mandy Cane Lane - Taskmaster - S21E01 - Cube Is Good.mp4
        ├── Mandy Cane Lane - Taskmaster - S21E01 - Cube Is Good.jpg
        └── Mandy Cane Lane - Taskmaster - S21E01 - Cube Is Good.nfo
```

- `Show - something` without `SxE`, where `Show` is already known, goes to that show's **Season 00** (specials). List official special numbers under `specials` in the config (for example from TheTVDB) and matching posts get those numbers and titles; the rest are numbered around them.
- Everything else goes to the show "Mandy Cane Lane", with one season per year, numbered in publishing order.
- Each show gets a generated poster with its name on a frame from one of its episodes. In Plex, shows are titled by the source show alone (`show_title_template`).
- Title, description (her post text), date, season/episode and thumbnail are embedded in the MP4 and also written as `.nfo` and `.jpg` sidecars.
- Videos linked in the post text (Google Drive, Dailymotion) are downloaded too, as the post's parts. When a host throttles (HTTP 429, Drive's download quota), the post waits 30 minutes, doubling up to a day, without using up its five attempts.

Videos are downloaded as-is from Patreon (typically 1080p H.264/AAC), so Plex can direct-play them.

## Setup

1. **Cookies:** log in to patreon.com in a browser, export cookies for `patreon.com` in Netscape format (for example with the *Get cookies.txt LOCALLY* extension) and save the file as `config/cookies.txt`.
   The session lasts several months, but logging out of that browser session kills it. Use a private window and close it without logging out.
2. **Config:** copy `config.template.yaml` to `config/config.yaml` and fill in the Plex part.
3. **Run:** use `compose.example.yml`. The container checks for new posts every `interval_minutes`.

Commands (`docker exec mandy mandy --config /config/config.yaml <command>`):

| Command | What it does |
|---|---|
| `check` | Verify the cookie |
| `plan -n 20` | Show how the latest 20 posts would be named, without downloading anything |
| `refresh-art` | Rewrite show titles, posters and backgrounds (after changing `show_title_template`) |
| `likes [--all] [--mark-watched]` | Refresh which posts you have liked on Patreon; optionally mark liked episodes as watched in Plex |
| `refresh-plots [--remove-orphans]` | Fill empty episode descriptions from the posts and clean the rest; optionally delete sidecars left without a video |
| `youtube-stats [--all]` | Update the YouTube list for the statistics page |
| `run` | Download new posts once |
| `loop` | Default: `run` every `interval_minutes` |

## Plex

One **TV Shows** library ("Mandy") with the **Plex NFO Series** agent and the **Plex TV Series** scanner, and two folders:

- `library_dir` as Plex sees it (`/Media01/Mandy`): the Patreon shows, written by this tool.
- Pinchflat's folder for her channel (`/Media01/Pinchflat/TV/Mandy Cane Lane - YouTube`): the show "Mandy Cane Lane - YouTube", a season per year. Pinchflat's media profile for her writes NFO files, with the template `/TV/{{ source_custom_name }}/{{ source_custom_name }}/{{ season_by_year__episode_by_date_and_index }} - {{ title }} [{{ id }}].{{ ext }}`.

The agent reads the `.nfo` sidecars, so titles, descriptions, dates, posters and episode thumbnails all show up, and Plex doesn't try to match the folders against real TV shows. This tool only looks at, cleans up and lists as Patreon the files under `library_dir` that it downloaded itself; Pinchflat's folder is left alone.

## Throttling

`rate_limit` caps the download speed and `pause_seconds` adds a random pause between videos, and `max_downloads_per_run` spreads a large backlog over several runs. Downloads are otherwise far faster than real-time playback (an hour of video in about two minutes), which is an unusual pattern for one account.

## Index page

The container serves an index page on `web_port` (default 8000), at mandy.flagan.net: every video, Patreon and YouTube, grouped by show (or newest first on `/kronologisk`), with links to the Patreon post or YouTube video and the Plex episode, whether you have watched it in Plex, and whether you have liked it on Patreon. Filters narrow it to what you haven't watched or liked, to missing posts, or to one source. "Watched, not liked" is listed at the top, so you can like what you have seen. Patreon posts that are missing (failed, queued, throttled) are listed where their episode would be.

The page has no login of its own; it is behind Cloudflare Access.

Downloads never play through Patreon's player, so her statistics never show you watching; a like is the signal she does get. Liking can't be automated: Patreon rejects like requests without the web app's CSRF token. Like status is read-only: each run checks every watched-but-not-liked post, plus 20 others not checked in the last week. The page's button re-checks the watched ones on demand. `likes --all` checks every downloaded post at once. YouTube doesn't let anyone else read your likes, so YouTube rows link to the video instead.

A like means you have seen the episode, often before it was downloaded, so liked episodes are marked as watched in Plex after each run (`likes --all --mark-watched` does it now). Each episode is marked once, so setting one back to unwatched in Plex sticks.

## Statistics page

`/statistikk` shows how much video she has made: hours and videos per month and year on Patreon and on YouTube (videos, livestreams and Shorts). It is in English and shows nothing private (no watched or liked status, no Plex links), so it can be made public on its own, e.g. a Cloudflare Access bypass for that one path, and shared with her.

The YouTube channel's lists give each video's length but not its date, so dates are looked up once per video and kept in `data/MandyCaneLane/youtube.json`. The loop refreshes the list daily and looks up at most 300 new videos at a time; `youtube-stats --all` fills it in one go (about 1–2 seconds per video).

## Monitoring

When the cookie expires, every run fails with `Patreon login expired`. Set `heartbeat_url` to an Uptime Kuma push monitor to be alerted. Export a new `cookies.txt`; the next run picks it up without a restart.

## State

`data/MandyCaneLane/state.json` records which posts are handled: `done`, `no_media` (text, image or poll posts), `no_access` (not visible to your tier, e.g. a post only for free members) or `failed` (retried up to 5 times). Delete a post's entry to download it again.
