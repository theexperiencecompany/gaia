# Alert-rule linting (`tools/alert-rules/`)

Runs [Cloudflare pint](https://github.com/cloudflare/pint) over the Grafana alert
rules in `infra/docker/observability/grafana/provisioning/alerting/alert-rules.yaml`.

Grafana has no equivalent of `promtool test rules`, so a rule built on a metric
nothing exports provisions cleanly, logs nothing and never fires. pint's
`promql/series` check is the closest guard we have. It runs in the
`alert-rules` CI lane (offline subset) and as a manual step against prod
Prometheus (the full set).

```bash
# Translate the Grafana rules into Prometheus rule YAML:
uv run tools/alert-rules/extract_promql.py -o /tmp/gaia-rules.yaml

# The checks CI runs — no Prometheus needed:
pint --offline --config config/pint.hcl lint /tmp/gaia-rules.yaml

# The checks that find a metric nothing exports — needs prod Prometheus on :9090
# (it is overlay-only; infra/docker/observability/CLAUDE.md has the tunnel):
pint --config config/pint.hcl lint --min-severity=info /tmp/gaia-rules.yaml
```

## Why an extractor

pint reads Prometheus-native rule YAML. Our rules are Grafana-managed, where the
PromQL is one node in a `data[]` array and the threshold is another. Keeping a
second, hand-written Prometheus copy of 25 rules would drift on the first edit —
which is the same class of bug as the one being guarded against — so the
translation is derived from the single source of truth on every run and thrown
away afterwards. Nothing generated is checked in.

The mapping, per rule:

| Grafana | Prometheus |
|---|---|
| `uid` | `alert` (stable, unique, and the runbook page name) |
| `data[refId: A].model.expr` | `expr`, wrapped in parens |
| `condition` node's `evaluator` | the comparison appended to `expr` (`gt 1` → `> 1`) |
| `for`, `labels` | `for`, `labels` verbatim |
| non-templated `annotations` | `annotations` |
| group `name` / `interval` | group `name` / `interval` |

Two translation decisions worth knowing:

**The threshold is folded into the expression.** Grafana keeps it in a separate
`threshold` node, so the extracted `expr` alone would have no condition at all —
pint's `alerts/comparison` would flag every rule, and `promql/impossible` and
`alerts/count` would have nothing to judge. Reducer `last` over an instant query
is the identity, so `A` + the evaluator is a faithful reconstruction. The
original expression is parenthesised first: a top-level `and`/`or` binds looser
than a comparison, so an unwrapped `a and b > 1` would compare only `b`.

**Templated annotations are dropped.** Grafana expands annotations with its own
engine, and its `$values.<ref>.Value` does not exist in Prometheus templates —
promtool rejects the whole file with `undefined variable "$values"`. Only
literal annotations (`runbook_url`, `__dashboardUid__`, `__panelId__`) survive.
The templated ones are Grafana's to validate; `infra/docker/observability/CLAUDE.md`
covers how.

## Fail-loud

A rule that quietly drops out of linting is the exact failure mode this exists to
prevent, so the extractor aborts the run — it never skips a rule. It fails on a
missing `uid` / `for` / `data[]`, a duplicate `refId` or `uid`, a `condition`
naming a refId that does not exist, a condition node that is not a `threshold`,
a threshold with more or fewer than one numeric condition, an evaluator with no
PromQL equivalent, and a chain from the threshold back to the query that passes
through anything other than a `reduce`/`last`.

Some of those are silent failures in Grafana too — a `condition` pointing at a
refId that does not exist provisions fine and only breaks at evaluation time.

When a new rule legitimately needs a different shape, teach the extractor that
shape deliberately. Do not make it tolerant.

## What CI does and does not catch

`pint --offline` runs only the checks that need no Prometheus connection.
pint's own list decides which those are (`--offline` disables everything in its
`OnlineChecks` set), so nothing here has to track it by hand:

- **offline, runs in CI** — `promql/syntax`, `promql/impossible`, `promql/nan`,
  `promql/fragile`, `promql/regexp`, `alerts/comparison`, `alerts/template`,
  `alerts/for`, `group/interval`, `rule/dependency`
- **needs a live Prometheus, manual only** — `promql/series` (**the
  metric-does-not-exist check**), `alerts/count`, `promql/rate`,
  `promql/counter`, `promql/vector_matching`, `labels/conflict`,
  `promql/range_query`, `promql/offset`, `promql/features`, `alerts/absent`,
  `alerts/external_labels`, `rule/duplicate`

CI therefore proves a rule is valid PromQL, not that it can ever fire. Run the
online pass before merging a new rule.

Note that `alerts/count` reports at `Information`, which `pint lint` hides
unless you pass `--min-severity=info`. That report — "this rule would have fired
0 times in the last week" — is half the value of the online run, so always pass
the flag.

`alerts/for` reports `for: 0m` as a redundant default. That is a translation
artifact, not a finding: Grafana requires `for` on every rule and rejects the
whole file without it. It stays at `Information` and never fails the lane.

## Independent cross-check

pint embeds Prometheus's own PromQL parser, so it is not a fully independent
opinion on whether the extracted file is a valid rule file. `promtool` is:

```bash
promtool check rules /tmp/gaia-rules.yaml
```

Not wired into CI — building promtool costs more than it adds once pint is
already parsing the same file with the same library.
