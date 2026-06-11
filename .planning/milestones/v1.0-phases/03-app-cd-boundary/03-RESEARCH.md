# Phase 3: App CD Boundary - Research

## Findings

The three app-owned runtime images are already pinned:

- `server-2`
- `replay-parser-2`
- `replays-fetcher`

The missing work is documentation and validation around the ownership boundary:
which repo owns builds, which repo owns Kubernetes apply, and how to update a
pinned staging image tag.

## Validation Architecture

Extend `scripts/validate-staging.py` to fail if GHCR app images use `:latest`
or are not pinned to an explicit tag.

## Research Complete
