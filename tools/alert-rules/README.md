# Alert-rule verification (`tools/alert-rules/`)

Verifies the Grafana alert rules in
`infra/docker/observability/grafana/provisioning/alerting/alert-rules.yaml` with
[Cloudflare pint](https://github.com/cloudflare/pint) and Prometheus's own
`promtool` — in CI and locally, via one command:

```bash
tools/alert-rules/verify.sh
```

Grafana's rules are managed objects, not Prometheus rule files, so neither tool
can read them directly. `extract_promql.py` derives a Prometheus-native rule file
from the single source of truth on every run — there is no second, hand-written
copy to drift. The derived file is thrown away after each run and never checked
in (`tools/alert-rules/gaia-rules.yaml` is gitignored).

The `verify.sh` pipeline, which is exactly what the `alert-rules` CI lane runs:

1. `uv run tools/alert-rules/extract_promql.py -o tools/alert-rules/gaia-rules.yaml --test-dir tools/alert-rules/tests` — translates every Grafana rule and **fails if any rule has no promtool test file** (or any test file has no rule). A rule without a test is a rule that "provisions cleanly and never fires" — the exact failure mode this exists to prevent.
2. `pint --offline` — PromQL validity and sanity (see the check split below).
3. `promtool check rules` — validates the derived rule file (pint embeds Prometheus's own parser, so this is a deliberately redundant cross-check).
4. `promtool test rules tools/alert-rules/tests/*.yaml` — **proves every rule fires** under its trigger fixture and **stays quiet** under its quiet fixture, honouring each rule's real `for` duration.

## The test suite (`tools/alert-rules/tests/`)

One `promtool test rules` file per rule (`<uid>.yaml`), in Prometheus's native
test format — no custom schema. Each file has:

- a **trigger** test — synthetic series at values that cross the rule's
  threshold, asserting the alert fires (with the exact label set and literal
  annotations, so a dropped `__dashboardUid__` or changed message also fails);
- a **quiet** test — values below the threshold, asserting `exp_alerts: []`, so
  an always-firing rule fails too.

The fixtures encode the exporter reality the rule depends on — e.g. the latency
fixtures use the exact `le` buckets from `apps/api/app/core/app_factory.py`. If
the fixture's `le` labels (which mirror `app_factory.py`) ever cap below the
rule's threshold, the trigger test fails — the p95-can-never-fire regression.
The fixture is a static snapshot, so a change to `app_factory.py` alone does not
re-run the lane; keep the fixture's bucket labels in sync when the app's buckets
change.

**New rules ship with a test.** The extractor's `--test-dir` check enforces it:
a rule without a matching `<uid>.yaml` aborts the run. Add the fixture in the
same change as the rule; copy an existing fixture as a template.

Two limits of what the fixtures can prove (both Grafana-only semantics that
`promtool` cannot model, so both are documented rather than papered over):

- `noDataState: Alerting` — the "no series at all → alert" path. Fixtures for
  those rules cover the value-present path (`up=0` / `probe_success=0` fires).
- `execErrState` and `DatasourceError` rendering — verified against a real
  Grafana, see `infra/docker/observability/CLAUDE.md` → "Verify against a real
  Grafana before shipping".

## Why an extractor

pint reads Prometheus-native rule YAML. Our rules are Grafana-managed, where the
PromQL is one node in a `data[]` array and the threshold is another. Keeping a
second, hand-written Prometheus copy of 25 rules would drift on the first edit —
which is the same class of bug as the one being guarded against — so the
translation is derived from the single source of truth on every run.

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

A rule that quietly drops out of verification is the exact failure mode this
exists to prevent, so the extractor aborts the run — it never skips a rule. It
fails on a missing `uid` / `for` / `data[]`, a duplicate `refId` or `uid`, a
`condition` naming a refId that does not exist, a condition node that is not a
`threshold`, a threshold with more or fewer than one numeric condition, an
evaluator with no PromQL equivalent, a chain from the threshold back to the
query that passes through anything other than a `reduce`/`last`, and any rule or
test file without a counterpart in the other (`--test-dir`).

Some of those are silent failures in Grafana too — a `condition` pointing at a
refId that does not exist provisions fine and only breaks at evaluation time.

When a new rule legitimately needs a different shape, teach the extractor that
shape deliberately. Do not make it tolerant.

## What CI does and does not catch

CI proves a rule is valid PromQL **and** that it fires and stays quiet against
synthetic data (`promtool test rules`). It cannot prove the metric exists with
matching labels, or that the threshold is reachable — those answers only live in
Prometheus, so they need the online pint pass against a LOCAL Prometheus holding
the relevant series before merging a new rule (no prod access needed):

```bash
# The checks that find a metric nothing exports — needs a local Prometheus on
# :9090 (scrape the pinned exporters, or feed it the metrics the rule needs):
pint --config config/pint.hcl lint --min-severity=info tools/alert-rules/gaia-rules.yaml
```

`pint --offline` (CI) runs only the checks that need no Prometheus connection —
`promql/syntax`, `promql/impossible`, `promql/nan`, `promql/fragile`,
`promql/regexp`, `alerts/comparison`, `alerts/template`, `alerts/for`,
`group/interval`, `rule/dependency`. The live pass adds `promql/series` (**the
metric-does-not-exist check**), `alerts/count`, `promql/rate`, `promql/counter`,
`promql/vector_matching`, `labels/conflict`, `promql/range_query`,
`promql/offset`, `promql/features`, `alerts/absent`, `alerts/external_labels`,
`rule/duplicate`.

Note that `alerts/count` reports at `Information`, which `pint lint` hides
unless you pass `--min-severity=info`. That report — "this rule would have fired
0 times in the last week" — is half the value of the online run, so always pass
the flag.

`alerts/for` reports `for: 0m` as a redundant default. That is a translation
artifact, not a finding: Grafana requires `for` on every rule and rejects the
whole file without it. It stays at `Information` and never fails the lane.

## Pinning

`verify.sh` uses the pinned tool images — `ghcr.io/cloudflare/pint:0.87.0` and
`prom/prometheus:v3.1.0` (the version prod runs) — so local and CI behaviour
cannot drift. CI installs the same two versions by other means and runs the
identical commands: pint via `go install github.com/cloudflare/pint/cmd/pint@v0.87.0`,
and promtool from the pinned GitHub release tarball (Prometheus v3's go.mod
declares `module github.com/prometheus/prometheus` without the `/v3` suffix, so
`go install ...@v3.1.0` is rejected by the Go tool at major version 3).
