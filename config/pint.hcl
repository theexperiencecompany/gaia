// pint (github.com/cloudflare/pint) config for the Grafana alert rules.
//
// pint reads Prometheus-native rule YAML, so it is always pointed at the output
// of `tools/alert-rules/extract_promql.py`, never at alert-rules.yaml directly.
//
// The `pint-alert-rules` CI lane runs `pint --offline`, which disables every
// check that needs to query a live Prometheus. pint's own list of online checks
// decides that, so nothing here has to be kept in sync by hand.
//
// The `prometheus` block below is only used by a manual run against prod. That
// run is what catches a rule built on a metric nothing exports (promql/series)
// and a rule that has never once crossed its threshold (alerts/count) — the two
// failures CI structurally cannot see. See
// infra/docker/observability/CLAUDE.md → "Linting rules with pint".

prometheus "prod" {
  // Prod Prometheus has no published port — it lives on the gaia-prod-shared
  // overlay network — so an online run tunnels it to localhost first. See
  // infra/docker/observability/CLAUDE.md → "Linting rules with pint".
  uri      = "http://localhost:9090"
  timeout  = "2m"
  required = true
}

rule {
  match {
    kind = "alerting"
  }

  // Estimate how often each rule would have fired over the last week. A rule
  // reporting 0 alerts is the signature of a threshold that cannot be reached —
  // it provisions cleanly, logs nothing, and is silent forever. `step` is
  // coarser than the 15s scrape_interval to keep the range queries cheap on a
  // 512m Prometheus.
  alerts {
    range   = "7d"
    step    = "5m"
    resolve = "5m"
  }
}
