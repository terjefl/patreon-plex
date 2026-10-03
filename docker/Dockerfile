FROM python:3.13-slim-bookworm

RUN apt-get update && apt-get -y install --no-install-recommends ffmpeg tzdata && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY patreon_plex patreon_plex

RUN pip install --no-cache-dir .

COPY docker/entrypoint.sh .
RUN chmod +x ./entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
CMD ["loop"]
