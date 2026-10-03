#!/bin/sh
set -e

# Patreon changes its site now and then; a fresh yt-dlp on every start keeps the extractor current.
if [ "${YTDLP_AUTO_UPDATE:-1}" = "1" ]; then
    pip install --no-cache-dir --quiet --upgrade "yt-dlp[default,curl-cffi]" || echo "yt-dlp update failed, using bundled version"
fi

exec patreon-plex --config "${CONFIG:-/config/config.yaml}" "$@"
