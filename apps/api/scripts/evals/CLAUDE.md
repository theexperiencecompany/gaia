# Writing evals

Rules for adding or changing cases in this harness. They exist because each one
was learned the expensive way — every "why" below is a real defect that shipped.

## The one rule

**A gate that cannot go red is not a test.** Before trusting a case, prove its
gates reject a wrong answer:

```bash
uv run --group backend python -m scripts.evals verify --suite <name>
```

This runs every case against deliberately worthless runs — one that produced
nothing, one that parrots the prompt back, and your own `counterfeit:` block if
you wrote one. It calls no model and no database, so run it constantly.

Categories it reports:

| verdict | meaning |
|---|---|
| BROKEN | a run producing NOTHING scored a pass. Always a defect. |
| INERT | declares a gate its suite never scores. The case can never PASS. |
| ungated | no gate and no judge criteria — nothing can fail it. |
| judge-only | no runtime gate; graded only when a run finalizes. Weak. |
| content-blind | passes an echo. Fine for a structural/absence case, not for a content one. |
| weak | one gate is fakeable, but another still catches the run. |

INERT is the mirror of BROKEN and was invisible until it bit us. `runner`
reads a declared gate back with `scores.get(gate, 0.0)`, so a gate the suite
never computes is a permanent 0.0 — the case is red whatever the agent did, and
the sweep called it *proven*, because an unscored gate rejects every forgery
too. `verify` now also asks whether each gate can go GREEN.

## Writing an assertion

**Assert the value where it is authoritative.** If the claim is "a todo now
exists", assert the database (`end_state`), not the prose. Prose assertions are
for what the user must be *told*.

**Never assert a token that can arrive by accident.** A case once asserted the
agent said `"what"` to prove it asked a question. The agent ignored the user and
built the wrong thing — but the workflow JSON it emitted contained "what", so
the gate went green. `"which channel"`, `"2,450.75"`, `priya@northwind.io` cannot
arrive by accident; `"what"`, `"the"`, `"done"` can.

**Never assert a word the prompt already contains.** The agent can satisfy it by
repeating the question back. `verify` reports these — they are acceptable only
beside a stronger gate.

**Pair a weak presence check with a discriminating absence check.** `"?"` proves
nothing (a reply that guesses, acts, then adds "Anything else?" satisfies it).
Pair it with `must_not_communicate: ["i've deleted", "i've booked"]` — the
past-tense completion claim the guessing failure actually emits.

**Absence is its own claim.** "Did it call X" cannot express "it must never call
X". Use `must_not_call_tools` / `must_not_communicate`. `min_calls: 0` means "at
least zero calls", which no run can fail — the loader rejects it.

## Gates

Declare them in `expected.score.gates`. A case passes only when **every** gate
passes, so one strong gate beside a weak one still fails correctly.

**`gates: []` is an auto-PASS.** `_status_from_scores` returns `passed` the
moment the list is empty — it never looks at a score. Judge criteria alone do
not gate anything at runtime. Every case declares at least one real gate.

Every gate lives once, in `core/gates.py`, and every suite dispatches through
it: `communicate`, `must_not_communicate`, `tool_call_correctness`,
`no_forbidden_tools`, `delegation`, `end_state`, `bubble_boundary`. A suite may
add its own in `EXTRA_GATES` — quality contributes `tool_card`,
`emoji_discipline`, `suggestion`, `openui` and the prompt-derived absolutes;
capability contributes `no_unauthorized_send`.

**A gate name nothing implements fails at load time**, by case id, before a
single model call is spent. It used to be a silent 0.0 that read as the agent
getting the answer wrong — capability re-implemented three gate names inline, so
a case declaring `no_forbidden_tools` was permanently red and its whole category
reported 0%.

**Prefer a mechanical gate to the judge.** If a prompt rule is stated as an
absolute — "never", "always", a named list — it is almost certainly checkable in
code. The emoji rule was being graded by a rubric judge that never once flagged
a violation sitting in plain text; as 20 lines of code it caught one on first
contact with real data. A judge emits a number for everything, so "no signal"
looks identical to "quality".

**But falsifiability beats determinism.** A deterministic check that cannot fail
is *worse* than a judge, because it carries the authority of a hard gate.
`OpenUICheck` returned 1.0 without reading anything whenever `openui: false`.

## Judge criteria

Use the judge only for genuine judgement — tone, empathy, whether a refusal
moralises, whether advice is concrete.

Criteria must be specific and falsifiable. "Is the answer good" grades nothing.
The judge is deliberately strict: 3/5 is a FAIL, fluency is not evidence, and
every verdict must quote the words that justify it.

Where a criterion restates a shipped prompt rule, compose it from the prompt
text (see `core/prompt_contracts.py` and `data/quality/openui.yaml`) so editing
the prompt cannot silently leave the eval grading a spec we no longer ship.

## Cases must be independent

Every case gets a fresh user. Never reuse an account across cases: state
accumulates, results become order-dependent, a later case can answer from memory
instead of doing the work, and concurrency becomes unsafe. Never hold per-case
data on the transport instance either — one instance serves every case, so that
is shared state.

## Running

```bash
python -m scripts.evals run --suite <name>                    # sequential, rotates providers
python -m scripts.evals run --suite <name> --concurrency 4    # pins ONE provider
python -m scripts.evals run --suite <name> --only case-a,case-b
python -m scripts.evals run --suite <name> --resume <run-id>  # skips finished cases
```

Concurrency pins one provider because the app's provider settings are
process-global; rotation is sequential-only.

## Statuses

`passed` · `failed` (graded wrong) · `errored` (never produced an answer) ·
`skipped`.

**An outage is not a wrong answer.** `errored` is unscored, excluded from
accuracy, and resumable. A backend being down raises `InfraError` and aborts the
run rather than journaling cases that never executed — a Postgres blip once
became a published 0/64 because 76 empty records were averaged in as zeros.

## Before you trust a number

- `verify` is clean for the suite.
- The publish gate passed — it cross-checks token sums against the cost
  tracker's own total, refuses to score a case that produced nothing, and
  rejects a cumulative token series.
- The category has enough cases. Never report a percentage below n=5; report raw
  counts instead. "Composition 100%" was two cases.
- The run used one provider, if you intend to compare it to another run.
