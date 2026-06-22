# Correction entry template

Append one block per correction to `<target-skill>/corrections-log.md` (in this skills repo). Heading
for human scanning, YAML for machine parsing. Field meanings: `references/journal-schema.md`.

```markdown
### <id> · <signal> · <class> · <section>

```yaml
id: SC-<YYYY-MM-DD>-<4hex>
date: <YYYY-MM-DD>
target_skill: <solidstats-skill-name>
repo: <server-2 | replays-fetcher | replay-parser-2 | web | n-a>
source: <agent-discovered | human-edit | free-form-prose>
signal: <divergence | gap | caused-bug | friction | preference>
class: <fact | preference>
generalized: <true | false>
section: <"§X" or "unmapped">
topic: <short-tag>
dev_change: >
  <what the skill says vs. what is true; for divergence carry the true fact>
code:
  file: <"path" or null>
  line: <N or null>
  source: <agent-snippet | head-besteffort | none>
  status: <negative-example | positive-example | needs-code-context | n-a>
  snippet: |
    <the few relevant lines, or omit>
rationale: >
  <the "why" and the class reasoning (why fact vs preference)>
status: open
signature: "<signal>|<section>|<canonical-description>"
```
```

## A filled example

```markdown
### SC-2026-06-22-7c1d · caused-bug · fact · §AA

```yaml
id: SC-2026-06-22-7c1d
date: 2026-06-22
target_skill: solidstats-shared-backend-ts-standards
repo: server-2
source: agent-discovered
signal: caused-bug
class: fact
generalized: false
section: "§AA"
topic: observability
dev_change: >
  §AA's logging example logs the full request object, which includes the auth header; following it
  leaked a bearer token into the logs. The rule should mandate redaction of the auth header.
code:
  file: "src/plugins/logging.ts"
  line: 42
  source: agent-snippet
  status: negative-example
  snippet: |
    req.log.info({ req }, 'incoming request')
rationale: >
  Following the rule as written produces a security defect — fact, fixable at one occurrence. Add a
  guardrail rather than deleting the logging guidance.
status: open
signature: "caused-bug|§AA|request logging leaks auth header"
```
```
