# Breaking the Code: The Adversarial Playbook

How to write tests that trash the implementation instead of congratulating it.

## Table of Contents

1. [The Mindset](#1-the-mindset)
2. [The Mutation Check, In Practice](#2-the-mutation-check-in-practice)
3. [The Scenario Hunt](#3-the-scenario-hunt)
4. [Attack Catalogue by Input Type](#4-attack-catalogue-by-input-type)
5. [Attack Catalogue by Code Shape](#5-attack-catalogue-by-code-shape)
6. [Deriving Assertions Without Peeking](#6-deriving-assertions-without-peeking)
7. [When the Attack Lands](#7-when-the-attack-lands)

---

## 1. The Mindset

You have two hats. Take off the author's hat.

| The author asks | The adversary asks |
|-----------------|--------------------|
| Does it work? | What makes it break? |
| Did I cover the branches? | What case has no branch at all? |
| Is the suite green? | What bug would slip through this green suite? |
| Does the test pass? | Can this test *ever* fail? |

A suite written with the author's hat on will pass forever, including on the day the code starts
returning wrong answers. That suite is worse than no suite, because it buys confidence it has not
earned.

**Green on the first run is a smell.** It usually means the assertion was reverse-engineered from
the code's current output, so the test and the code agree by construction. When a new test passes
immediately, do not celebrate — go verify it can fail.

---

## 2. The Mutation Check, In Practice

The rule: **you have not written a test until you have seen it fail.**

### The loop

```
1. Write the test.
2. Break the production code with one realistic mutation.
3. Run the test.
     RED   -> the test is real. Continue.
     GREEN -> the test is blind. Rewrite it. It does not test what you think it tests.
4. Restore the production code (git checkout / undo the edit).
5. Run the test. It must be GREEN.
6. Confirm no mutation survives in the working tree.
```

Step 4 is not optional and step 6 is not paranoia — a mutation left behind is a shipped bug.

### Choosing a mutation

Mutate the way a tired engineer would introduce a bug — not by deleting the whole function (that is
the weakest possible mutation and almost any test catches it).

```python
# Production
def can_send(quota_used: int, quota_limit: int) -> bool:
    if quota_used >= quota_limit:
        return False
    return True
```

| Mutation | Test that survives it is blind to... |
|----------|--------------------------------------|
| `>=` → `>` | The exact-limit boundary (`used == limit`) |
| `>=` → `<` | Total inversion — caught by almost anything |
| `return False` → `return True` | Whether you assert on the negative case at all |

If your only test is `assert can_send(0, 10) is True`, mutation #1 keeps it green. The test is
blind to the only interesting input in the function. The test that matters is
`assert can_send(10, 10) is False`.

**A test that only survives the dumbest mutation is a dumb test.** Aim at the subtle ones.

### Automating it

Where a mutation-testing tool exists, use it instead of doing this by hand:

```bash
# Python
uv run mutmut run --paths-to-mutate app/services/quota.py

# TypeScript
pnpm exec stryker run
```

A surviving mutant is a hole in the suite, stated precisely. Hand-mutation is the fallback when no
tool is wired up — not the preferred method.

---

## 3. The Scenario Hunt

Run this **after** the feature is built, before writing assertions. The output is the test plan.

For every input, dependency, and piece of state the code touches, ask: *what value or timing would
this code not survive?* Write down each answer. Then write a test for it.

Work the surfaces in this order — earlier ones catch more bugs per test:

1. **Boundaries** — off-by-one is still the most common bug in production code.
2. **Failure modes of dependencies** — the network is not reliable; the code usually assumes it is.
3. **Bad inputs** — the code trusts its callers far more than it should.
4. **State and ordering** — retries, double-submits, out-of-order calls, partial writes.
5. **Authorization** — the check that is missing, not the one that is present.
6. **Volume and duplicates** — assumptions about size that hold on dev data and break in prod.

Each scenario the code fails to survive is either a **bug to fix at the root** or a **requirement to
make explicit** (validate, reject, document). Both are wins. Neither is "adjust the test until it
passes."

---

## 4. Attack Catalogue by Input Type

Concrete values to throw at a function. Not exhaustive — a prompt to think with.

### Strings
`""` · whitespace only · a single character · unicode and emoji · combining characters · RTL text ·
`"null"` / `"undefined"` / `"None"` as literal text · leading/trailing whitespace · newlines and
tabs · a string 10× longer than any assumed limit · SQL/HTML/shell metacharacters if the value is
ever interpolated

### Numbers
`0` · negative · the exact boundary · boundary ± 1 · `float("inf")` / `NaN` · a value that overflows
the column type · a float where an int is assumed · a numeric string (`"5"`) where a number is
assumed

### Collections
`[]` · `[x]` (single element) · duplicates · `None` / `null` *inside* the collection · an element of
the wrong type · a collection larger than the page size · an ordering the code did not expect

### Optionals and absence
`None` · a key missing from the dict entirely (vs. present with value `None` — these are different
bugs) · an empty string where `None` was expected · a field the caller never sends

### Time
Exactly `now` · in the past · in the future · a naive datetime where an aware one is required · a
DST boundary · timezone-shifted input · an expiry that lapses *during* the operation

### Identifiers
An ID that does not exist · an ID belonging to a different user · a soft-deleted record · a
malformed UUID · an ID that exists but in the wrong state

---

## 5. Attack Catalogue by Code Shape

Read the production code and match its shape to the attacks below.

### It calls an external service

The dependency will fail. Prove the code copes.

```python
def test_send_returns_error_when_provider_times_out():
    with patch("app.tools.gmail.client.send") as mock:
        mock.side_effect = httpx.TimeoutException("timeout")
        result = send_email(to="x@y.com", body="hi")
        assert result.error == "Failed to send: timeout"
        assert result.sent is False
```

Attack each of: timeout · connection refused · HTTP 500 · HTTP 429 with a `Retry-After` · a 200 with
a **malformed body** · a 200 with an empty body · a response missing the field the code reads. The
last three are the ones nobody writes and the ones that page you at 3am.

### It has a retry or a fallback

The fallback path is production code and it is almost never tested.

- Does the retry actually retry? Force two failures, then a success.
- Does it stop retrying? Force permanent failure — assert it gives up rather than looping forever.
- Is the operation idempotent under retry? Force a retry after a *partial* success and assert the
  side effect happened exactly once, not twice.

### It writes to a database or emits a side effect

- Call it twice with the same input. Should the second call be rejected, be a no-op, or duplicate?
  Whatever the requirement says — assert it. This catches the double-send class of bug.
- Force a failure *between* two writes and assert the first was rolled back or compensated.

### It has an `if` on a permission, role, or ownership

- Call it as a user who does not own the resource. Assert it is **rejected**, not merely that the
  owner is allowed. Testing only the allow-path is how authorization bugs ship.

### It parses or validates input

- Feed it the malformed variant of every field. Assert a specific, informative error — not a bare
  `Exception`, not a silent `None`.
- Feed it a valid-looking value of the wrong type.

### It is async or concurrent

Stay inside what a QA tester would actually hit — a double-clicked button, a retried request, a
duplicate webhook — not microsecond-level interleavings.

- Fire the same request twice concurrently. Assert one wins and state stays consistent.
- Cancel mid-flight. Assert no partial state is left behind.

### It transforms or aggregates data

- Empty input. Single item. Items that sum to zero. A `None` in the middle of the list.
- Assert the *actual computed values*, not just the shape. `assert len(result) == 3` catches almost
  nothing; `assert result[1].total == Decimal("19.99")` catches real arithmetic bugs.

---

## 6. Deriving Assertions Without Peeking

The trap: run the code, see it return `{"status": "ok", "count": 0}`, and write
`assert result == {"status": "ok", "count": 0}`. That test now agrees with the code by
construction. If the count is wrong, the test enshrines the wrong count. It can never fail for the
reason you care about.

**Derive the expected value from the requirement, independently of the implementation.**

```python
# WRONG — reverse-engineered from the code's current output
result = calculate_invoice(items)
assert result.total == 107.5   # copied from the failing test output until it passed

# RIGHT — computed from the requirement, by hand
# Requirement: 2 × $50 widgets, 7.5% tax, $2.50 flat shipping
#   subtotal 100.00 + tax 7.50 + shipping 2.50 = 110.00
result = calculate_invoice(items)
assert result.total == Decimal("110.00")
```

If your hand-computed value disagrees with the code, you have found either a bug or a
misunderstanding of the requirement. **Do not** change the assertion to match the code until you know
which. That single reflex — "the test disagrees, so the test must be wrong" — is how bugs get
tested-in and shipped.

---

## 7. When the Attack Lands

The test goes red on code that looks correct. This is the skill working. What happens next decides
whether it was worth running.

**Do:**
- Treat red as a finding. Reproduce it, confirm the expected value against the requirement.
- Fix the production code at the root (see `CLAUDE.md` — no workarounds, no symptom patches).
- Keep the test. It is now a regression guard that has already earned its place.

**Never:**
- Loosen the assertion until it passes (`assert result.total > 0`).
- Wrap it in `pytest.mark.skip` / `xfail` / `it.skip` to get the suite green.
- Change the expected value to whatever the code emitted.
- Delete the test because "it's probably testing the wrong thing."

Turning the suite green by weakening tests converts a caught bug into a shipped bug **and** destroys
the test that would have caught it next time. It is strictly worse than never writing the test.

If a test fails and you genuinely cannot tell whether the code or the test is wrong, **stop and
ask** — do not resolve the ambiguity by guessing in the direction of green.
