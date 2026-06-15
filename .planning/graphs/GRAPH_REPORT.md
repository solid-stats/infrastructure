# Graph Report - .  (2026-06-15)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 127 nodes · 178 edges · 22 communities (9 shown, 13 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `cbfc14c2`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]

## God Nodes (most connected - your core abstractions)
1. `require()` - 10 edges
2. `require()` - 7 edges
3. `validate()` - 7 edges
4. `validate_manifest_shape()` - 7 edges
5. `validate_rendered_secrets()` - 7 edges
6. `require()` - 6 edges
7. `ValidationError` - 6 edges
8. `run()` - 6 edges
9. `_top_value()` - 5 edges
10. `_check_no_secret_values()` - 5 edges

## Surprising Connections (you probably didn't know these)
- `ValidationError` --inherits--> `Exception`  [EXTRACTED]
  scripts/validate-edge.py →   _Bridges community 3 → community 2_
- `ValidationError` --inherits--> `Exception`  [EXTRACTED]
  scripts/validate-s3-lifecycle.py →   _Bridges community 2 → community 4_
- `ValidationError` --inherits--> `Exception`  [EXTRACTED]
  scripts/validate-staging.py →   _Bridges community 2 → community 0_

## Import Cycles
- None detected.

## Communities (22 total, 13 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.17
Nodes (23): CompletedProcess, _has_yaml_content(), _is_comment_or_blank(), _load_s3_lifecycle_validator(), metadata_name(), # NOTE: These helpers are intentionally minimal, line-based parsers — NOT a full, Load the standalone validate-s3-lifecycle.py as a module so CI enforces     the, Offline gate for CUT-01..04: assert cutover script and runbook exist with requir (+15 more)

### Community 1 - "Community 1"
Cohesion: 0.24
Nodes (15): Path, _check_namespace(), _check_no_clusterrole(), _check_no_secret_values(), _check_priority_class(), _check_render_errors(), Fail if a Secret document carries a populated stringData/data value., Fail if a namespaced resource declares a namespace outside the allowed obs set. (+7 more)

### Community 2 - "Community 2"
Cohesion: 0.20
Nodes (12): Exception, Validate config/nginx/sites-available/grafana-stats-staging-solid-stats.conf., Validate config/nginx/sites-available/errors-stats-staging-solid-stats.conf., Validate docs/obs-edge-bootstrap.md exists and shared Phase 07 systemd artifacts, Validate scripts/bootstrap-obs-edge.sh structure and idempotency markers., # NOTE: the literal dangerous flag is intentionally NOT written here — only the, require(), validate_bootstrap_script() (+4 more)

### Community 3 - "Community 3"
Cohesion: 0.22
Nodes (12): Validate systemd drop-in and failure-handler units shape (D-4, D-5)., Validate bootstrap-edge.sh idempotency and security markers., Validate teardown-edge.sh has required cleanup markers., Validate config/nginx/sites-available/stats-staging-solid-stats.conf structure., Validate shell scripts syntax and required markers., require(), validate_bootstrap_idempotency_markers(), validate_nginx_vhost() (+4 more)

### Community 4 - "Community 4"
Cohesion: 0.36
Nodes (6): Validate config/s3/backups-lifecycle.json structure (S3-01, S3-02)., Validate scripts/apply-s3-lifecycle.sh syntax and required markers., require(), validate_apply_script_syntax(), validate_lifecycle_json(), ValidationError

### Community 5 - "Community 5"
Cohesion: 0.48
Nodes (5): validate-phase-16.sh script, assert(), assert_not_found(), start_port_forward(), stop_port_forward()

### Community 6 - "Community 6"
Cohesion: 0.83
Nodes (3): cutover.sh script, required(), rollback()

### Community 7 - "Community 7"
Cohesion: 1.00
Nodes (3): validate-phase-13.sh script, assert(), check_target_health()

### Community 8 - "Community 8"
Cohesion: 0.83
Nodes (3): validate-phase-15.sh script, assert(), assert_not()

## Knowledge Gaps
- **11 isolated node(s):** `apply-s3-lifecycle.sh script`, `backup-postgres-now.sh script`, `bootstrap-edge.sh script`, `kubeconfig-setup.sh script`, `resource-preflight.sh script` (+6 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ValidationError` connect `Community 0` to `Community 2`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Why does `ValidationError` connect `Community 3` to `Community 2`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **What connects `apply-s3-lifecycle.sh script`, `backup-postgres-now.sh script`, `bootstrap-edge.sh script` to the rest of the system?**
  _32 weakly-connected nodes found - possible documentation gaps or missing edges._