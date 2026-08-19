---
status: diagnosed
trigger: >-
  Prometheus currently reports kube-state-metrics, postgres-exporter, and
  alloy targets as down. Determine why without changing cluster state.
created: 2026-08-20
updated: 2026-08-20T02:00:29+07:00
---

# Debug Session: Observability Targets Down

## Symptoms

- Expected behavior: Prometheus scrapes healthy kube-state-metrics,
  postgres-exporter, and alloy targets.
- Actual behavior: all three existing targets report `up == 0` while other
  targets, including the newly restored cAdvisor target, are healthy.
- Error messages: not yet collected from the Prometheus targets API.
- Timeline: confirmed live on 2026-08-20 after restoring cAdvisor collection;
  the last known-good time is not yet established.
- Reproduction: query `up` for the three jobs, inspect Prometheus scrape
  errors, then correlate them with Services, Endpoints, pods, events, logs,
  and NetworkPolicies.

## Current Focus

- bug_class: bohrbug (each target is currently down deterministically).
- known_pattern_candidate: phase-17 network-isolation planning requires explicit
  Prometheus-to-target allows before default-deny.
- hypothesis: confirmed — monitoring's default-deny ingress selects alloy,
  kube-state-metrics, and postgres-exporter, while no policy allows the
  Prometheus pod to their metrics ports.
- test: compared current target API errors, ready EndpointSlices and pods,
  listener logs, all relevant applied policies, the direct Prometheus-to-Service
  and Prometheus-to-pod probes supplied by the parent investigator, and the
  Loki control target.
- expecting: supported — service and direct endpoint connections reject while
  listeners and endpoints are healthy; the explicitly ingress-permitted Loki
  target is up.
- reasoning_checkpoint:
    hypothesis: Monitoring namespace default-deny ingress rejects new
      Prometheus connections to alloy:12345, kube-state-metrics:8080, and
      postgres-exporter:9187 because only egress allowances were applied.
    confirming_evidence:
      - The target API reports connection refused for all three resolved Service
        IPs; each target has a ready EndpointSlice and Ready pod.
      - The live policies have default-deny-ingress with podSelector {},
        Prometheus egress on all three ports, and no target ingress allow;
        Loki has an ingress allow and its scrape is up.
      - kube-state-metrics and postgres-exporter log listeners on their metrics
        ports, Alloy readiness succeeds on 12345, and parent read-only probes
        reject both Service and endpoint addresses from Prometheus.
    falsification_test: A current ingress policy selecting any affected target
      and allowing the Prometheus pod on its scrape port, or a failed scrape of
      Loki despite its corresponding ingress allow, would refute this mechanism.
    fix_rationale: Add one minimal target-ingress policy that selects the three
      metrics workloads and admits only Prometheus on TCP 8080, 9187, and 12345;
      this restores the missing direction without widening egress or disabling
      namespace isolation.
    blind_spots: Diagnose-only scope forbids the counterfactual policy change,
      so post-change recovery remains unverified. The current node-level
      enforcement process was not inspected; Phase 17 verification already
      records active kube-router NetworkPolicy chains and a blocked deny probe.
    candidate_causes:
      - config: confirmed missing target ingress permits under default deny.
      - code: ruled out target listener/process failures by current readiness
        and listener logs.
      - data: ruled out static target or Service selector drift by matching
        current resolved Service IPs, ready endpoints, and target API addresses.
      - environment: pod restarts on 2026-08-02 created fresh connections and
        explain when the persistent policy defect became visible.
    and_gate: no — the configuration omission alone blocks the present scrape
      flows; the synchronized restarts are an exposure/timing condition, not a
      second necessary root cause.
- next_action: return the diagnosis; do not apply the proposed NetworkPolicy.

## Evidence

- timestamp: 2026-08-20T01:54:10+07:00
  checked: semantic knowledge-base recall in the infrastructure MemPalace wing
  found: Phase 17 planning and PITFALLS explicitly require Prometheus scrape
    allows before namespace default-deny; the recorded warning signs include
    down targets after a NetworkPolicy change.
  implication: missing target ingress is a prior hypothesis candidate, not a
    diagnosis; it must be tested against live state.

- timestamp: 2026-08-20T01:55:10+07:00
  checked: repository manifests for Prometheus, the three target workloads, and
    monitoring NetworkPolicies
  found: Prometheus statically scrapes alloy:12345, kube-state-metrics:8080,
    and postgres-exporter:9187. Policy 2 selects every monitoring pod for
    default-deny ingress; Policy 7 permits only Prometheus egress to those
    ports. Explicit ingress permits exist for Grafana, Prometheus, and Loki,
    but not for the three target label selectors.
  implication: repository configuration contains the exact asymmetry predicted
    by the shared-policy hypothesis. Live applied-policy and workload state are
    still required to confirm it is the current cause.

- timestamp: 2026-08-20T01:56:02+07:00
  checked: live monitoring Services, EndpointSlices, selected Pods, warning
    events, and NetworkPolicy inventory through read-only kubectl queries
  found: alloy (10.43.183.137:12345 -> 10.42.0.154), kube-state-metrics
    (10.43.227.115:8080 -> 10.42.0.151), and postgres-exporter
    (10.43.190.163:9187 -> 10.42.0.139) each have a ready EndpointSlice and a
    Running, Ready pod. The live policy inventory has namespace-wide
    default-deny ingress plus Prometheus scrape egress, but no named target
    ingress policy; the only current warning event is unrelated node-exporter
    DNS configuration truncation.
  implication: Service selector drift, missing endpoint, unready pod, and a
    target-pod warning event do not explain the three down targets. The same
    live policy shape as the repository is present.

- timestamp: 2026-08-20T01:56:46+07:00
  checked: Prometheus /api/v1/targets through the read-only Kubernetes Service
    proxy, filtered to alloy, kube-state-metrics, and postgres-exporter
  found: all three targets are health=down with current resolved Service IPs
    and exact errors: alloy 10.43.183.137:12345, kube-state-metrics
    10.43.227.115:8080, and postgres-exporter 10.43.190.163:9187 each return
    connect: connection refused.
  implication: DNS resolution and Prometheus static target configuration are
    working. The failure is a TCP rejection at or after Service routing, common
    to all three targets.

- timestamp: 2026-08-20T01:57:47+07:00
  checked: full live specs for the default-deny, Prometheus scrape egress,
    Loki ingress, and Prometheus ingress policies; safe target logs; and a
    Prometheus target API control query for Loki
  found: default-deny-ingress has an empty pod selector and no allow clauses.
    Prometheus has outbound TCP permits for 8080, 9187, and 12345, but no
    policy permits its ingress to any of the three target pods. In contrast,
    Loki explicitly permits any monitoring pod on 3100 and its identical
    Prometheus scrape is up. kube-state-metrics logs it is listening on
    [::]:8080; postgres-exporter logs it is listening on [::]:9187; alloy is
    Ready on a readiness probe to 12345. A postgres-exporter missing optional
    config-file warning precedes its successful listener start.
  implication: the working Loki control demonstrates that Prometheus, its DNS,
    and its namespace routing work when target ingress is allowed. The three
    exporter processes are available on their service ports, so the shared
    missing-ingress rule—not an exporter process failure—explains the TCP
    refusals.

- timestamp: 2026-08-20T01:58:46+07:00
  checked: target-specific Pod conditions, last container termination state,
    and target-specific events
  found: all target pods have Ready=True and ContainersReady=True, no target
    events, and their latest container terminations were simultaneous at
    2026-08-02T11:14:33Z (alloy and its reloader, kube-state-metrics, and
    postgres-exporter).
  implication: the common restart is consistent with the timing of fresh
    rejected connections after NetworkPolicy was already active; it does not
    identify a target-specific runtime failure.

- timestamp: 2026-08-20T01:59:29+07:00
  checked: cross-agent read-only connectivity evidence, correlated with the
    current endpoint-to-pod mappings gathered in this investigation
  found: from the Prometheus pod, both the three Service IPs and their matching
    endpoint pod IPs reject TCP connections. The referenced endpoints are the
    live ready addresses recorded above.
  implication: kube-proxy Service routing is not the source of the refusal;
    it reaches the same policy-protected endpoint path as a direct pod request.

- timestamp: 2026-08-20T02:00:29+07:00
  checked: parent-provided Phase 17 live-validation confirmation, integrated
    without further privileged inspection
  found: Phase 17 recorded active KUBE-NWPLCY chains and a blocked deny probe;
    the project network-policy documentation identifies kube-router as the
    enforcer. Current direct pod-IP probe refusals match that accepted blocked
    behavior.
  implication: the live NetworkPolicy enforcement branch is confirmed; the
    missing ingress allow is causally sufficient for the current refusals.

## Eliminated

- hypothesis: The static Prometheus addresses, DNS, Service selectors, or
  EndpointSlices are stale or wrong.
  evidence: Prometheus resolves each configured Service name to its current
    ClusterIP, and each Service selects one ready EndpointSlice/pod at the
    expected port.
  timestamp: 2026-08-20T01:59:29+07:00

- hypothesis: One or more exporter processes are absent, unready, or not
  listening on their scrape ports.
  evidence: All three pods are Running and Ready; kube-state-metrics and
    postgres-exporter log listeners on 8080 and 9187, and Alloy's readiness
    probe succeeds on 12345.
  timestamp: 2026-08-20T01:59:29+07:00

- hypothesis: Prometheus lacks the needed outbound access or monitoring
  namespace routing is generally broken.
  evidence: The applied egress policy permits Prometheus on every affected
    port, and the same Prometheus instance successfully scrapes Loki through
    Loki's explicit ingress allow.
  timestamp: 2026-08-20T01:59:29+07:00

- hypothesis: An event-driven target workload failure explains the shared
  outage.
  evidence: No target-specific events exist; their simultaneous 2026-08-02
    restarts precede healthy Ready states and explain only the exposure timing.
  timestamp: 2026-08-20T01:59:29+07:00

## Resolution

- root_cause: One shared configuration defect, not three independent exporter
  failures: `default-deny-ingress` selects every pod in `monitoring`, including
  alloy, kube-state-metrics, and postgres-exporter. The applied policy set
  grants Prometheus only egress to TCP 12345, 8080, and 9187; it supplies no
  reciprocal ingress allow on those target pods. New Prometheus TCP scrapes are
  therefore rejected. The synchronized 2026-08-02 restarts exposed the existing
  defect by forcing fresh connections.
- fix: Not applied (diagnose-only). Add a minimal ingress NetworkPolicy in
  `k8s/observability/95-netpol-monitoring.yaml` selecting the three target
  workloads and allowing only the Prometheus server pod to TCP 12345, 8080, and
  9187. Preserve the current default-deny and all egress restrictions.
- verification: Diagnosis verified with the live Prometheus target API, current
  Services/EndpointSlices/pods/events, safe listener logs, applied NetworkPolicy
  specs, direct Prometheus-to-Service and Prometheus-to-endpoint probe evidence,
  and a working Loki control target. No fix or post-fix verification was run.
- files_changed: `.planning/debug/observability-targets-down.md` only.
