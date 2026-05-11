---
status: resolved
trigger: "Full staging replay ingest promoted 30 replay records, but replay-parser-2 failed 29 parse jobs with json.decode and produced no statistics."
created: 2026-05-10
updated: 2026-05-11
---

# Debug Session: replay-json-decode

## Symptoms

- Expected behavior: controlled full run downloads replays, parser consumes jobs, parser_results and aggregate stats are populated, then old-vs-new statistics diff can run.
- Actual behavior: fetcher completed and server-2 promoted 30 replays, but parser_results, player_stats, squad_stats, and commander_side_stats remained empty.
- Error messages: parse_jobs showed `json.decode|json_decode|Replay JSON could not be decoded|29`.
- Timeline: observed during manual staging full run on 2026-05-10.
- Reproduction: run one-off `replays-fetcher` Job from `cronjob/replays-fetcher` after backup gate; parser jobs fail after server-2 publishes them.

## Current Focus

- hypothesis: replays-fetcher stores an HTML/detail page or otherwise non-OCAP JSON payload from `https://sg.zone/replays/<id>` instead of the actual OCAP JSON replay payload expected by replay-parser-2.
- test: inspect replays-fetcher source URL construction and a fetched object sample/content-type without exposing secrets.
- expecting: stored objects are small/non-JSON or source detail pages contain a separate replay JSON download URL.
- next_action: gather source and live payload evidence, then implement the minimal fetcher fix.

## Evidence

- `https://sg.zone/replays/<id>` returns the HTML replay detail page.
- The detail page exposes the OCAP JSON file through `body[data-ocap]`; the
  actual payload URL is `/data/<data-ocap>.json`.
- The fixed `replays-fetcher` image
  `ghcr.io/solid-stats/replays-fetcher:542b43d2c6141e95f1dfe13207c9944ef5913159`
  staged 30 replay records with `replayTimestamp` values.
- After server-2 fix/deploy and manual rotation seeding, a full staging run
  produced server-2 public stats: 30 parsed replays, 498 players, 498 player
  stat rows, 36 commander-side rows, and 377 bounty players.

## Eliminated

- Parser JSON decoding was not caused by replay-parser-2 contract handling; the
  stored raw objects were the wrong source payload before the fetcher fix.
- The post-fix zero player stats were not caused by SteamID absence alone. The
  immediate live blocker was missing manual `rotations`; without a matching
  rotation server-2 returns `missing_rotation` before aggregate recalculation.

## Resolution

- root_cause: replays-fetcher downloaded replay detail HTML from
  `/replays/<id>` instead of the OCAP JSON data file. A second stats blocker was
  server-2 identity resolution requiring existing SteamID/canonical identity
  even though current parser artifacts do not include Steam IDs.
- fix: replays-fetcher now derives and fetches `/data/<ocap>.json`, derives
  replay timestamps from source filenames, and infra pins the fixed image.
  server-2 now resolves no-SteamID parser players via active manual nickname
  history first, then fallback canonical identities by observed name.
- verification: replays-fetcher and server-2 full local verifies passed in their
  app repos; staging restore + fetcher + parser + server-2 recalculation
  completed against backup `20260510T073635Z`.
- files_changed: `k8s/staging/50-replays-fetcher.yaml`.
