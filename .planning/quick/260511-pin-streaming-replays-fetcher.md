# Pin streaming replays-fetcher

## Goal

Run the full replay ingest with `replays-fetcher` streaming page-by-page so raw
S3 upload and staging happen while discovery continues.

## Change

- Pin staging `replays-fetcher` to
  `ghcr.io/solid-stats/replays-fetcher:8395fbc58df3422a235d0a198e34eaf460491f21`.
- Configure `REPLAY_SOURCE_MAX_PAGES=786` for the full source corpus.
