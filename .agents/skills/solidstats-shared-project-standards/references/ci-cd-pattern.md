# CI/CD Pattern — SolidStats Standard

This reference covers the standard GitHub Actions pipeline structure used across SolidStats
repos. Read this when creating or modifying a `.github/workflows/` file.

---

## Canonical workflow structure

Every SolidStats repo uses a single workflow file (typically `cd.yml`) with this shape:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main, master]
  workflow_dispatch:

concurrency:
  group: <repo-name>-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read
  packages: write   # required for GHCR push

jobs:
  verify:
    name: Verify
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      # ... setup, install, run verification suite

  image:
    name: Build and push image
    runs-on: ubuntu-latest
    timeout-minutes: 30   # 40 for Rust (longer compile)
    needs: [verify]
    if: github.event_name != 'pull_request'
    steps:
      # ... Docker build and GHCR push
```

---

## Concurrency

Always include the `concurrency` block with `cancel-in-progress: true`. This prevents
duplicate runs accumulating when commits are pushed quickly. Use a per-ref group so PRs and
branches each have their own concurrency slot:

```yaml
concurrency:
  group: <repo-name>-${{ github.ref }}
  cancel-in-progress: true
```

---

## Verify job

The verify job is the gate. It must pass before the image job runs, and it runs on every PR.
It includes all checks that can be run without Docker (except integration test services, which
are spun up inline):

**TypeScript repos (server-2, replays-fetcher):**
1. Setup pnpm 11 and Node 25 with caching (`pnpm/action-setup@v4`, `actions/setup-node@v4`)
2. `pnpm install --frozen-lockfile`
3. Start integration services via Docker Compose (PostgreSQL 17, RabbitMQ 4, MinIO)
4. Run `pnpm run verify`:
   - `prettier --check .`
   - `eslint .`
   - `tsc --noEmit`
   - `pnpm test` (unit tests)
   - `pnpm test:integration` (Docker-backed tests)
   - OpenAPI drift check (where applicable)
   - `pnpm test:coverage` (V8, 100% gates)
5. Tear down services

**Rust repo (replay-parser-2):**
1. Install Rust 1.95.0 with minimal profile + clippy + rustfmt (`dtolnay/rust-toolchain@v1`)
2. Cargo cache (`Swatinem/rust-cache@v2`)
3. `cargo fmt --all -- --check`
4. `cargo clippy --workspace --all-targets -- -D warnings`
5. `cargo test --workspace`

**Node version pinning (TS repos):**
```yaml
- uses: pnpm/action-setup@v4
  with:
    version: 11
- uses: actions/setup-node@v4
  with:
    node-version: 25
    cache: pnpm
```

---

## Image job

The image job builds the Docker image and pushes to GHCR. It runs only on push to
`main`/`master` (not on PRs), and only after verify passes.

```yaml
image:
  needs: [verify]
  if: github.event_name != 'pull_request'
  steps:
    - uses: actions/checkout@v4
    - uses: docker/login-action@v3
      with:
        registry: ghcr.io
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}
    - uses: docker/metadata-action@v5
      id: meta
      with:
        images: ghcr.io/${{ github.repository }}
        tags: |
          type=sha
          type=ref,event=branch
    - uses: docker/build-push-action@v6
      with:
        context: .
        push: true
        tags: ${{ steps.meta.outputs.tags }}
        labels: ${{ steps.meta.outputs.labels }}
```

Image tags: commit SHA (`sha-<short>`) + branch name. This gives both a stable per-branch
tag and a unique per-commit tag for traceability.

---

## Dockerfile conventions

All SolidStats services use multi-stage Docker builds:

**TypeScript (Node 25 Alpine):**
```dockerfile
# Stage 1: dependencies
FROM node:25-alpine AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN corepack enable pnpm && pnpm install --frozen-lockfile

# Stage 2: build
FROM deps AS builder
COPY . .
RUN pnpm run build

# Stage 3: production runtime
FROM node:25-alpine AS runner
WORKDIR /app
RUN addgroup --system --gid 65532 nonroot && \
    adduser --system --uid 65532 nonroot
COPY --from=builder --chown=nonroot:nonroot /app/dist ./dist
COPY --from=builder --chown=nonroot:nonroot /app/node_modules ./node_modules
USER 65532:65532
EXPOSE 3000
CMD ["node", "dist/server.js"]
```

**Rust (Bookworm + Debian Slim):**
```dockerfile
# Stage 1: builder
FROM rust:1.95.0-bookworm AS builder
WORKDIR /app
COPY . .
RUN cargo build --release --bin replay-parser-2

# Stage 2: runtime
FROM debian:bookworm-slim
RUN addgroup --system --gid 65532 nonroot && \
    adduser --system --uid 65532 nonroot
COPY --from=builder --chown=nonroot:nonroot /app/target/release/replay-parser-2 /usr/local/bin/
USER 65532:65532
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD replay-parser-2 healthcheck --url http://127.0.0.1:8080/readyz
ENTRYPOINT ["replay-parser-2"]
CMD ["worker"]
```

Key conventions:
- Non-root user `65532:65532` (matches distroless nonroot UID)
- Alpine for Node, Debian Slim for Rust (smaller than full Debian, has libc for Rust binaries)
- Multi-stage to keep final image small (no dev dependencies, no Rust toolchain)
- `EXPOSE` documents the port; actual binding via env var `PORT` or hardcoded in the app

---

## Local services via Docker Compose

Integration tests that need real infrastructure spin up services via Docker Compose. The
standard test service layout:

```yaml
# docker-compose.yml (development)
services:
  postgres:
    image: postgres:17-alpine
    ports: ["15432:5432"]           # host port offset avoids conflicts with local installs
    environment:
      POSTGRES_DB: solidstats_dev
      POSTGRES_USER: solidstats
      POSTGRES_PASSWORD: solidstats

  rabbitmq:
    image: rabbitmq:4-management-alpine
    ports: ["5673:5672", "15673:15672"]

  minio:
    image: minio/minio
    ports: ["9000:9000", "9001:9001"]
    command: server /data --console-address ":9001"
```

Port convention: host port = container port + offset (e.g. `15432` instead of `5432`) to
avoid conflicts with locally-installed databases.

---

## Infrastructure repo pipeline (validate + SSH deploy)

The `infrastructure` repo uses a different pipeline shape — it validates manifests and deploys
to staging over SSH; it does **not** build images.

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main, master]
  workflow_dispatch:

concurrency:
  group: infrastructure-staging-${{ github.ref }}
  cancel-in-progress: true

jobs:
  validate:
    name: Validate
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - name: Validate manifests
        run: python3 scripts/validate-staging.py

  deploy:
    name: Deploy staging
    runs-on: ubuntu-latest
    timeout-minutes: 20
    needs: [validate]
    if: github.event_name != 'pull_request'
    environment: staging          # gates on GitHub environment protection rules
    steps:
      - uses: actions/checkout@v4
      - name: Install SSH key
        uses: shimataro/ssh-key-action@v2
        with:
          key: ${{ secrets.CD_SSH_PRIVATE_KEY }}
          known_hosts: unnecessary
      - name: Trust deploy host
        run: ssh-keyscan -p ${{ secrets.CD_SSH_PORT }} ${{ secrets.CD_SSH_HOST }} >> ~/.ssh/known_hosts
      - name: Render secrets
        env:
          POSTGRES_PASSWORD: ${{ secrets.POSTGRES_PASSWORD }}
          # ... other secrets from GitHub environment
        run: python3 scripts/render-staging-secrets.py
      - name: Apply manifests and wait for rollouts
        run: bash scripts/deploy-staging.sh
```

**Key differences from app repos:**
- No `image` job — infrastructure never builds container images.
- Uses `environment: staging` to gate deployment behind GitHub environment protection rules
  and inject secrets at deploy time.
- `validate` job runs on every PR; `deploy` runs only on push to `main`/`master`.
- Secrets are rendered from GitHub environment variables into Kubernetes `Secret` manifests
  at deploy time via `render-staging-secrets.py`; no secret values are stored in git.
- Deployment over SSH: `kubectl apply` is executed remotely on the k3s VPS; the workflow
  never has direct cluster access.

**Manifest validation** (`scripts/validate-staging.py`) checks:
- Required YAML files exist in `k8s/staging/`
- All image tags are pinned to explicit SHAs (no `latest`, no branch tags)
- Required Kubernetes Secret keys are present
- All Deployments/StatefulSets declare resource requests and limits
- All containers have readiness + liveness probes

**Image SHA pinning rule:** the `infrastructure` repo pins every app image to a full commit
SHA (e.g. `ghcr.io/solid-stats/server-2:sha-3866f6b`). When an app repo ships a new image,
the infrastructure repo's manifest must be updated with the new SHA — the pipeline rejects
`latest` or any mutable tag during validation.
