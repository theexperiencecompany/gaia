# infra/docker/observability

Alert rules for the production stack. **Only `grafana/provisioning/alerting/alert-rules.yaml`
lives here.** The rest of the observability config — `prometheus.yml`,
`loki-config.yaml`, `promtail-config.yaml`, `blackbox.yml`, `grafana/Dockerfile`,
the dashboards, datasources, contact points, notification policies and
templates — moved to the private `theexperiencecompany/gaia-infra` repo, because
this repo is public and prod topology is not.

Grafana provisioning is **baked into an image** (`grafana/Dockerfile`, in
gaia-infra), not bind-mounted — so any change ships only via a rebuild of
`ghcr.io/theexperiencecompany/gaia-grafana`.

## Layout

| Path | What it is | Where |
|---|---|---|
| `grafana/provisioning/alerting/alert-rules.yaml` | All alert rules | here |
| `prometheus.yml` | Scrape jobs. Adding a target here is a prerequisite for alerting on it. | gaia-infra |
| `blackbox.yml` | Blackbox exporter modules (`http_2xx`: 5s timeout, only 200 counts as success) | gaia-infra |
| `grafana/provisioning/alerting/contact-points.yaml` | Slack + email receivers | gaia-infra |
| `grafana/provisioning/alerting/notification-policies.yaml` | Routing and repeat cadence | gaia-infra |
| `grafana/provisioning/alerting/templates.yaml` | Slack message templates | gaia-infra |
| `grafana/provisioning/dashboards/*.json` | Dashboards (uid is referenced by alert rules) | gaia-infra |

## Adding an alert rule

### 1. Confirm the metric actually exists

Before writing anything, prove the metric is emitted **by the exporter version
pinned in the prod compose (`gaia-infra`)**. A rule built on a metric nothing exports
provisions cleanly, never fires, and never complains — it is worse than no rule,
because it reads as coverage. Run that exporter locally and scrape it with a
local Prometheus (or read the exporter's docs for the exact version), then prove
the rule's selector matches mechanically with pint's `promql/series` check
before you open the PR — see "Linting rules with pint" below.

Watch for two specific traps that have already bitten us here:

- **`up{job="postgres"}` and `up{job="redis"}` scrape the exporter sidecars, not
  the databases.** Either database can be completely down while `up` stays `1`.
  Use `pg_up` / `redis_up` for the database itself.
- **RabbitMQ's default `/metrics` is aggregated only.** Per-queue series live on
  the separate `rabbitmq_detailed` job. `sum()` over a series that does not
  exist yields empty, which with `noDataState: OK` means silence forever.

### 2. Write the rule

Every rule follows the same three-node shape: `A` is the instant PromQL query,
`B` reduces it to a single value (`reducer: last`), `C` compares `B` against the
threshold. `condition: C`.

```yaml
- uid: gaia-thing-broken           # stable, kebab-case, prefixed gaia-
  title: Thing is broken           # plain language, not the metric name
  condition: C
  data: [...]                      # A / B / C as above
  noDataState: OK                  # see step 4
  execErrState: Error
  for: 5m                          # REQUIRED — omitting it fails the whole file
  annotations:
    summary: >-
      {{ if $values.B }}...{{ else }}...{{ end }}
    description: >-
      What breaks for users, and the first thing to check.
    runbook_url: https://docs.lab.heygaia.io/production/runbooks/gaia-thing-broken
    __dashboardUid__: gaia-overview
    __panelId__: "3"
  labels:
    severity: critical             # critical | warning — drives routing
    service: api                   # api | arq_worker | postgres | redis | ...
```

`title` is the Slack message title and the first thing on-call reads. Name the
problem, not the metric: "API is returning server errors", not "API 5xx error
rate high".

### 3. The three silent-failure traps

All three have shipped to production here. None of them error — they just
produce a broken message, or no message.

**Always use `$values.<ref>.Value`, never bare `$values.<ref>`.** `$values.B` is
a struct. Piping it into `humanizePercentage` fails with `can't convert
template.Value to float`, and Grafana's error path *keeps the raw template text
as the annotation* — on-call sees the literal `{{ $values.B | humanizePercentage }}`
in Slack, with no error surfaced anywhere.

**Format every number, and guard every `$values` reference.**

```gotemplate
{{ if $values.B }}{{ printf "%.2f" $values.B.Value }}%{{ else }}...{{ end }}
```

Unformatted, `{{ $values.B.Value }}` prints full float64 precision
(`1.3333333333333333`). Unguarded, it renders the literal Go error
`%!f(<nil>)` whenever the rule hits DatasourceError or NoData — which is to say,
the summary breaks at exactly the moment monitoring breaks. The guard is safe
at a measured value of `0` (a struct is always truthy in Go templates); it is
falsy only when the ref is genuinely absent. The `else` branch should say the
rule could not be evaluated, not restate the threshold.

Formatting reference: `printf "%.2f"` for rates and seconds, `printf "%.0f"` for
counts, `humanizePercentage` for `0..1` ratios (**it multiplies by 100** — never
use it on a value the PromQL already scaled), `humanize1024` for bytes,
`humanizeDuration` for seconds-until-something.

**Dashboard links are annotations, not rule fields.** Written as top-level
`dashboardUid:` / `panelId:` they are silently dropped by file provisioning and
no link ever renders. They must be `__dashboardUid__` and `__panelId__` inside
`annotations:`, with `__panelId__` a **quoted string**. Set both or neither:
`__panelId__` alone is inert, and `__dashboardUid__` alone **aborts the entire
alerting provisioner at startup**, taking every rule with it.

One more: only expressions without `sum()` carry per-series labels. A rule that
aggregates collapses to a single unlabeled series, so `{{ $labels.instance }}`
renders empty. Reference labels only on non-aggregating rules.

### 4. Choose `noDataState` and `execErrState` deliberately

These decide what happens when the rule *cannot* be evaluated, and the right
answer differs by rule type. A probe going NoData means something real (the
target vanished); a counter going NoData usually just means no traffic. Setting
`noDataState: Alerting` on the wrong rule produces false pages; setting it to
`OK` on the wrong rule produces a silent blind spot.

### 5. Write the runbook

Every rule links to `https://docs.lab.heygaia.io/production/runbooks/<uid>`,
sourced from `theexperiencecompany/internal-docs` at
`docs/production/runbooks/<uid>.mdx`. A rule without a runbook is unfinished —
the alert tells you something is wrong, the runbook is what makes it
actionable. Register the new page in `docs/docs.json` navigation.

### 6. Verify before shipping

Do not trust reading the YAML. Provisioning is permissive: a bogus `condition`
refId, an unresolvable `datasourceUid`, and a dropped dashboard field all
provision **silently** and fail later at evaluation time.

**Every rule ships with a promtool test.** `tools/alert-rules/tests/<uid>.yaml`
proves the rule fires under a trigger series and stays quiet under a quiet
series, honouring the real `for` duration. The extractor's `--test-dir` check
rejects any rule without one, so a rule "that provisions cleanly and never
fires" can no longer ship. Run the whole verification pipeline — extract +
coverage check, pint offline, `promtool check rules`, `promtool test rules` —
in one command, and it is the same pipeline CI runs:

```bash
tools/alert-rules/verify.sh
```

That proves the rule's logic. Then confirm it against a real Grafana — the
checks below catch the Grafana-side silent failures the rule test cannot
(provisioning, annotation survival, template rendering):

```bash
# from a gaia-infra checkout:
docker build -t gaia-grafana docker/observability/grafana
docker run --rm -p 3000:3000 \
  -e GF_SECURITY_ADMIN_PASSWORD=admin \
  -e GRAFANA_ALERT_EMAIL=dev@example.com \
  gaia-grafana
```

Then confirm, against the running instance:

```bash
# every rule provisioned, and annotations survived
curl -su admin:admin localhost:3000/api/v1/provisioning/alert-rules | jq '.[].title'
curl -su admin:admin localhost:3000/api/v1/provisioning/alert-rules \
  | jq '.[] | {uid, dash: .annotations.__dashboardUid__}'

# templates and contact points
curl -su admin:admin localhost:3000/api/v1/provisioning/templates | jq '.[].name'
```

The contact points read the Slack webhook from
`$__file{/run/secrets/gaia_grafana_slack_webhook}`; create a dummy file at that
path in the container to let provisioning complete.

To see what a message will actually look like, point the webhook at a local HTTP
sink and let a rule fire against the `grafana-testdata-datasource` — that is the
only path that exercises Grafana's real annotation expander end to end.

## Linting rules with pint

[pint](https://github.com/cloudflare/pint) is a Prometheus rule linter. It reads
Prometheus-native rule YAML, so `tools/alert-rules/extract_promql.py` derives
that from this file first — each rule's `refId: A` expression plus its threshold,
translated into one alerting rule. Nothing is generated into the tree; the
translation is thrown away after each run. The extractor aborts on any rule it
cannot translate rather than skipping it, because a rule that silently drops out
of linting is the failure mode all of this exists to prevent.

The `alert-rules` CI lane (and `tools/alert-rules/verify.sh`) runs four stages:
extraction with a `--test-dir` coverage check, `pint --offline`, `promtool
check rules`, and `promtool test rules` against the per-rule fixtures in
`tools/alert-rules/tests/`. The last one is what proves a rule can actually
fire; the fixtures are required for every rule.

```bash
uv run tools/alert-rules/extract_promql.py -o /tmp/gaia-rules.yaml

# What the `alert-rules` CI lane runs — no Prometheus needed:
pint --offline --config config/pint.hcl lint /tmp/gaia-rules.yaml
```

### CI cannot catch the bug this file keeps warning about

CI proves each rule is valid PromQL (pint's offline checks: syntax errors,
queries that can never match, sampling functions that make alerts flap,
regexp matchers with no metacharacters) and that it fires against synthetic
series (`promtool test rules`). It cannot tell you whether a metric exists,
because that answer only lives in Prometheus. **`promql/series` is the check
that catches a rule built on a metric nothing exports, and it needs a live
server.** So do the online pass against a LOCAL Prometheus before merging a new
rule — no prod access needed.

Boot a local Prometheus that scrapes the pinned exporters from the prod compose
(`docker/docker-compose.prod.yml` in the private `gaia-infra` repo), or that
holds representative series for the metrics the new rule needs, on
`localhost:9090`, then lint against it:

```bash
# extract the rules, then prove the server is up before trusting promql/series
uv run tools/alert-rules/extract_promql.py -o /tmp/gaia-rules.yaml
curl -s localhost:9090/api/v1/query?query=up | head -c 200   # prove the server first
pint --config config/pint.hcl lint --min-severity=info /tmp/gaia-rules.yaml
```

That `curl` is not optional — it is the difference between two readings that
look identical. A broken tunnel or wrong target makes `promql/series` report
**every** rule in the file as missing; a genuinely empty result means the
metric really is absent. Resolve any connectivity/query error first — if the
`curl` fails or the server is the wrong one, nothing else the online run says
is trustworthy. Only when the server responds cleanly does "no series" mean
"the metric does not exist."

The online run adds, on top of the offline set: `promql/series` (metric never
existed, or existed and disappeared, or has no series matching your label
matchers), `alerts/count` (how many times the rule would have fired in the last
week — **0 is a signal to investigate threshold reachability and data
coverage**, not proof the threshold is unreachable: a new rule, sparse
incidents, or missing history all also read 0),
`promql/rate` and `promql/counter` (a `rate()` over a gauge is valid PromQL and
always wrong; offline pint cannot tell a counter from a gauge because that
metadata lives in Prometheus), `promql/vector_matching`, and `labels/conflict`.

`--min-severity=info` is not optional either: `alerts/count` reports at
`Information` and is hidden without it.

One finding is expected noise: `alerts/for` calls `for: 0m` a redundant default.
True in Prometheus, false here — Grafana rejects the whole file without a `for`.
It stays at `Information` and never fails anything.

`tools/alert-rules/README.md` has the full check split and the details of the
Grafana → Prometheus translation.

## Notification routing and cadence

`notification-policies.yaml` controls how often an alert reaches Slack:

- `group_wait` — delay before the first message for a new group, so instances of
  one rule batch together.
- `group_interval` — delay before a follow-up message when new alerts join an
  existing group.
- `repeat_interval` — how often a still-firing alert is re-sent.

Grouping is by `grafana_folder` + `alertname`, so **instances of one rule batch
together**. Different rules batch **only** when they share the same `incident`
label (route 2 below); everywhere else an incident that trips five rules
produces five separate Slack threads, each repeating on its own timer. Keep
that in mind when adding a rule that will fire alongside existing ones.

Routing and repeat cadence (see `notification-policies.yaml` — the first
matching route wins):

- DatasourceError / DatasourceNoData → `critical-slack-email`, grouped by
  `alertname`, repeats 6h. One "monitoring is broken" thread, whatever the
  severity of the affected rules.
- `incident: availability` → `critical-slack-email`, grouped by `incident`,
  group_wait 90s so one outage batches into a single thread, repeats 1h.
- Remaining `severity: critical` → `critical-slack-email` (Slack **and** email),
  repeats 12h.
- Everything else (root) → `slack-alerts` (Slack only), repeats 24h.

The cadences are deliberately slow: warnings and criticals describe states that
move over days, and the availability route's faster 1h repeat is the "act now"
tier.

## Slack message templates

`templates.yaml` defines `gaia.slack.title` and `gaia.slack.message`, referenced
from the Slack receivers in `contact-points.yaml`.

**Never point a Slack receiver at `slack.default.text`.** That built-in is
defined as the empty string upstream — Alertmanager expects operators to
override it, and Grafana's default set never redefines it. Using it produces a
Slack message with a title and a completely empty body. This shipped to
production and went unnoticed, because the alerts *looked* like they were
arriving.

Notification templates run through Alertmanager's engine, whose function map is
much smaller than the one available in rule annotations — there is no
`humanize*` and no `query`. Format values in the rule's annotations, not here.
