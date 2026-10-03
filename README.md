# patreon-plex

Download the Patreon videos you have access to and file them as a Plex-friendly TV library.

> You need to be a paying patron with access to the posts. This tool only downloads what your own account can already watch on patreon.com, for personal viewing.

Posts with `SxE` in the title, like `Taskmaster - S21 E1 - Cube Is Good`, become proper episodes of their own show:

```
Mandy Cane Lane - Taskmaster/
├── tvshow.nfo
├── poster.jpg
└── Season 21/
    ├── Mandy Cane Lane - Taskmaster - S21E01 - Cube Is Good.mp4
    ├── Mandy Cane Lane - Taskmaster - S21E01 - Cube Is Good.jpg
    └── Mandy Cane Lane - Taskmaster - S21E01 - Cube Is Good.nfo
```

- `Show - something` without `SxE`, where `Show` is already known, goes to that show's **Season 00** (specials).
- Everything else goes to a show named after the creator, with one season per year, numbered in publishing order.
- Title, description, date, season/episode and thumbnail are embedded in the MP4 and also written as `.nfo` and `.jpg` sidecars (read by Jellyfin, Infuse and Kodi).

Videos are downloaded as-is from Patreon (typically 1080p H.264/AAC), so Plex can direct-play them.

## Setup

1. **Cookies:** log in to patreon.com in a browser, export cookies for `patreon.com` in Netscape format (for example with the *Get cookies.txt LOCALLY* extension) and save the file as `config/cookies.txt`.
   The session lasts several months, but logging out of that browser session kills it. Use a private window and close it without logging out.
2. **Config:** copy `config.template.yaml` to `config/config.yaml` and adjust it.
3. **Run:** use `compose.example.yml`. The container checks for new posts every `interval_minutes`.

Commands (`docker exec patreon-plex patreon-plex --config /config/config.yaml <command>`):

| Command | What it does |
|---|---|
| `check` | Verify the cookie |
| `plan -n 20` | Show how the latest 20 posts would be named, without downloading anything |
| `run` | Download new posts once |
| `loop` | Default: `run` every `interval_minutes` |

## Plex

Create a **TV Shows** library pointing at the library folder, and choose the **Personal Media Shows** agent, so Plex doesn't try to match the folders against real TV shows. Turn on *Local Media Assets* so posters and episode thumbnails are used.

## Monitoring

When the cookie expires, every run fails with `Patreon login expired`. Set `heartbeat_url` to an Uptime Kuma push monitor to be alerted. Export a new `cookies.txt`; the next run picks it up without a restart.

## State

`data/state.json` records which posts are handled: `done`, `no_media` (text or poll posts), `no_access` (higher tier) or `failed` (retried up to 5 times). Delete a post's entry to download it again.
