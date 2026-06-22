# Signal taxonomy and the fact/preference class

Capture sets two fields that drive everything downstream: `signal` (what kind of divergence) and
`class` (fact or preference, which sets the promotion threshold). This file defines both and how each
signal routes.

## Table of contents
- [1. The two classes](#1-the-two-classes)
- [2. The five signals](#2-the-five-signals)
- [3. Assigning the class](#3-assigning-the-class)
- [4. Routing each signal at promote](#4-routing-each-signal-at-promote)

---

## 1. The two classes

The class is the single most important field — it decides whether one occurrence is enough.

- **fact** — objectively verifiable as right or wrong. The skill names a path/import/method/command
  that does not exist or is wrong; the skill contradicts itself; following the skill produced a bug.
  A known falsehood does not need three repeats to be worth fixing. → **eligible to promote at one
  occurrence.**
- **preference** — taste or style with no hard correctness. "Better to name it this way", "this rule
  reads ambiguously", "I'd structure this differently." One witness is a noisy sample. → **promote
  only after three** (rule of three).

When genuinely unsure, default to **preference** — the cost of waiting for a second witness is low;
the cost of rewriting a shared skill from one opinion is high.

## 2. The five signals

### divergence — the skill is wrong about a fact
The skill states X; the real code or the correct practice is Y. The classic case: a convention names
a file/dir/import/method that the repo does not use.
- Class: **fact**.
- Evidence: the *true* fact (the real path/method), not necessarily a code snippet. Record it in
  `dev_change`; add a `file:line` in the consuming repo if one proves it.
- Example: `solidstats-server-ts-conventions` says deps live in `deps.py`; server-2 wires them in
  `di/`.

### gap — a real pattern no rule covers
Working in the repo surfaces a recurring pattern the skill is silent on. Not that the skill is wrong
— that it is incomplete.
- Class: **fact** when the pattern is canonical/agreed (it is simply missing); **preference** when
  it is a judgment call about whether the pattern *should* be the standard.
- Evidence: the pattern, with code.
- Example: every service in server-2 wraps external calls in a typed adapter, but no conventions rule
  states it.

### caused-bug — following the rule produced a defect
The agent obeyed the skill and the result was a bug, or the rule actively steers toward one.
- Class: **fact**. This is the highest-value signal — a rule that causes bugs is worse than a missing
  rule.
- Evidence: the offending code **and** the bug (symptom or failing test).
- Routing: qualify or fix the rule, and prefer adding a guardrail (a "don't do X because it causes
  Y" note) over a bare deletion.

### friction — the rule is ambiguous or contradictory
The rule is unclear, internally contradictory, or contradicts another rule, and that cost real time.
- Class: **fact** when it is a genuine internal contradiction (two rules cannot both hold);
  **preference** when it is merely "could be clearer."
- Evidence: optional — name the two conflicting passages, or the ambiguity.
- Routing: clarify the rule (or the shared standard, if the ambiguity lives there).

### preference — a stylistic improvement
A better way to phrase, name, or structure something, with no correctness stake.
- Class: **preference** (always).
- Evidence: optional, example only.
- Routing: only after rule of three; below that it stays as warming evidence.

## 3. Assigning the class

Decision order:
1. Did following the skill cause a bug? → `caused-bug`, **fact**.
2. Is the skill's statement objectively false (wrong path/method/command, or self-contradiction)? →
   `divergence` or `friction`, **fact**.
3. Is a real, agreed pattern simply missing? → `gap`, **fact**.
4. Otherwise it is a judgment call about what the standard *should* be → **preference** (`gap`,
   `friction`, or `preference` signal as fits).

Record the reasoning in `rationale` — it is decisive when PROMOTE adjudicates an edge call.

## 4. Routing each signal at promote

| Signal | Default target | Edit shape |
|--------|----------------|-----------|
| divergence | the target skill (or the shared standard if the wrong fact lives there) | correct the statement |
| gap | the target skill's matching section, or a new section if `unmapped` | add/extend a rule |
| caused-bug | the target skill | qualify the rule + add a guardrail note |
| friction | the target skill, or the shared standard if the ambiguity is shared | clarify / reconcile |
| preference | the target skill | adjust phrasing/structure, additively |

A correction whose true home is a `solidstats-shared-*-standards` skill (because the wrong/ambiguous
rule is *shared*, not stack-specific) routes there, not to the per-stack skill — the same delegation
the skills already use. State the routing in one line and let the user redirect.
