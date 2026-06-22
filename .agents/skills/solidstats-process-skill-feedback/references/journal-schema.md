# Journal schema, cluster signature, and regression-eval shape

This is the contract the loop depends on. Capture writes it; promote reads it. Keep entries
machine-parseable (stable field names) **and** human-readable — the log is a Markdown file the team
diffs in git, next to the skill it teaches.

## Table of contents
- [1. The normalized correction entry](#1-the-normalized-correction-entry)
- [2. Field reference](#2-field-reference)
- [3. The cluster signature](#3-the-cluster-signature)
- [4. The regression-eval case](#4-the-regression-eval-case)

---

## 1. The normalized correction entry

Each correction is one block appended to `<target-skill>/corrections-log.md` (in this skills repo).
A Markdown heading for scanning, a YAML fence for parsing.

```markdown
### SC-2026-06-22-a3f9 · divergence · fact · §4

```yaml
id: SC-2026-06-22-a3f9
date: 2026-06-22
target_skill: solidstats-server-ts-conventions
repo: server-2                 # server-2 | replays-fetcher | replay-parser-2 | web | n-a
source: agent-discovered       # agent-discovered | human-edit | free-form-prose
signal: divergence             # divergence | gap | caused-bug | friction | preference
class: fact                    # fact (promote@1) | preference (promote@3)
generalized: false             # true only for a stated principle, not an instance
section: "§4"                  # target skill's section/slug, or "unmapped"
topic: di                      # short tag
dev_change: >
  Conventions §4 says deps are wired in deps.py, but server-2 wires them in di/ (see
  src/di/container.ts). The rule names a file that does not exist in this repo.
code:
  file: "src/di/container.ts"
  line: 1
  source: agent-snippet        # agent-snippet | head-besteffort | none
  status: positive-example     # negative-example | positive-example | needs-code-context | n-a
  snippet: |
    export const container = buildContainer({ ... })
rationale: >
  Pure factual error — the skill points at a path that isn't there. Fixable at one occurrence.
status: open                   # open | promoted | discarded
signature: "divergence|§4|deps wired in di/ not deps.py"
```
```

> The example shows a real ```` ```yaml ```` fence nested in this doc; write it normally in the log.

## 2. Field reference

| Field | Meaning | Notes |
|-------|---------|-------|
| `id` | `SC-<date>-<4-hex>` | Stable; lets a promotion cite exact sources |
| `target_skill` | Which skill this teaches | Resolved per SKILL.md §C; must be in-scope |
| `repo` | Which consuming repo surfaced it | Provenance; `n-a` for a shared-standard-only fact |
| `source` | How it arrived | `agent-discovered` is the SolidStats norm |
| `signal` | One of the five | `references/signal-taxonomy.md` §2 |
| `class` | `fact` or `preference` | **Drives the threshold** — §A.3 of SKILL.md |
| `generalized` | A stated rule, not an instance | Relaxes the code requirement |
| `section` | Target skill's section slot | `unmapped` if it fits no section (signals the taxonomy may need one) |
| `dev_change` | The core observation: what the skill said vs. what is true | For `divergence` this carries the true fact |
| `code.*` | Bound code | §G of SKILL.md — source priority and the HEAD caveat |
| `code.status` | How to read the snippet | `negative-example` = should-flag; `positive-example` = should-not-flag/already-correct |
| `rationale` | The "why" + the class reasoning | Decisive at promotion |
| `status` | Lifecycle | `open` until promoted or discarded |
| `signature` | Cluster key | See below |

## 3. The cluster signature

The rule of three (for preferences) counts **patterns**, not byte-identical entries. The signature
is the cluster key:

```
signature = "<signal>|<section>|<canonical-description>"
```

- `signal` and `section` are exact-match buckets.
- `canonical-description` is a short normalized phrase for *the same underlying issue*, written so
  three phrasings collapse to one. "deps wired in di/ not deps.py" should absorb "deps.py is wrong,
  it's di/" and "container lives in di/, conventions say deps.py".

At promote time, clustering is **semantic**: group entries whose `(signal, section)` match and whose
descriptions mean the same thing, then show the cluster to the user before counting it. `fact`
entries do not need clustering to reach a count (they promote at one) — but still de-dup so a single
fact logged twice isn't proposed twice.

## 4. The regression-eval case

Optional, recommended for `code-review`/`conventions` targets. When a capture binds code, append one
JSON object (one line) to `<target-skill>/regression-evals.jsonl`:

```json
{"id": "SC-2026-06-22-a3f9", "section": "§4", "expect": "should-not-flag", "input_file": "src/di/container.ts", "snippet": "export const container = buildContainer({ ... })", "note": "deps wired in di/ not deps.py"}
```

- `expect`: `should-flag` (from a `gap`/`caused-bug` negative example) or `should-not-flag` (from a
  positive example / corrected code).
- `severity`: expected bucket when `should-flag`; omit otherwise.
- `id` ties the case back to its journal entry so a promotion can graduate it into the target skill's
  core `evals/evals.json` when the rule lands.

These run on demand or right before a promotion — never on an always-run path.
