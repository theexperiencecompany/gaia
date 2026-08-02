# infra/docker/observability

Prometheus, Loki, Promtail, Blackbox and Grafana config for the production
stack. Grafana provisioning is **baked into an image** (`grafana/Dockerfile`),
not bind-mounted — so any change here ships only via a rebuild of
`ghcr.io/theexperiencecompany/gaia-grafana`.

## Layout

| Path | What it is |
|---|---|
| `prometheus.yml` | Scrape jobs. Adding a target here is a prerequisite for alerting on it. |
| `blackbox.yml` | Blackbox exporter modules (`http_2xx`: 5s timeout, only 200 counts as success) |
| `grafana/provisioning/alerting/alert-rules.yaml` | All alert rules |
| `grafana/provisioning/alerting/contact-points.yaml` | Slack + email receivers |
| `grafana/provisioning/alerting/notification-policies.yaml` | Routing and repeat cadence |
| `grafana/provisioning/alerting/templates.yaml` | Slack message templates |
| `grafana/provisioning/dashboards/*.json` | Dashboards (uid is referenced by alert rules) |

## Adding an alert rule

### 1. Confirm the metric actually exists

Before writing anything, prove the metric is emitted **by the exporter version
pinned in `docker-compose.prod.yml`**. A rule built on a metric nothing exports
provisions cleanly, never fires, and never complains — it is worse than no rule,
because it reads as coverage. Query prod Prometheus, or read the exporter's docs
for that exact version.

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

```
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

### 6. Verify against a real Grafana before shipping

Do not trust reading the YAML. Provisioning is permissive: a bogus `condition`
refId, an unresolvable `datasourceUid`, and a dropped dashboard field all
provision **silently** and fail later at evaluation time.

```bash
docker build -t gaia-grafana infra/docker/observability/grafana
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

## Notification routing and cadence

`notification-policies.yaml` controls how often an alert reaches Slack:

- `group_wait` — delay before the first message for a new group, so instances of
  one rule batch together.
- `group_interval` — delay before a follow-up message when new alerts join an
  existing group.
- `repeat_interval` — how often a still-firing alert is re-sent.

Grouping is by `grafana_folder` + `alertname`, so **instances of one rule batch,
but different rules never do** — an incident that trips five rules produces five
separate Slack threads, each repeating on its own timer. Keep that in mind when
adding a rule that will fire alongside existing ones.

`severity: critical` routes to `critical-slack-email` (Slack **and** email) and
repeats hourly; everything else goes to Slack only and repeats every 4h.

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
