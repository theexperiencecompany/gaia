---
name: code-mode-scripting
description: How to run integration work as ONE efficient bash script (gaia.execute) — schema-first, batched, delegated to a spawned subagent when heavy. Read before writing any script that calls GAIA tools.
target: executor
---

# Code-Mode Scripting

Python scripts you run through `bash` can call GAIA integration tools directly:

```python
from gaia import execute, schema
emails = execute("GMAIL_FETCH_EMAILS", {"max_results": 50, "query": "is:unread"})
```

This is the cheapest way to do multi-call or data-heavy integration work: payloads
stay in Python variables instead of the conversation, and one script replaces a
long chain of tool calls. Use it well or not at all.

## When to reach for a script

- Three or more integration calls that feed each other, any pagination loop, or
  any filtering/aggregation/joining over tool outputs.
- NOT for a single call with a small result — plain `execute` from the
  conversation is cheaper than a shell round trip.

## Delegate heavy scripting to a spawned subagent

Script-heavy work belongs in `spawn_subagent`, not in your own loop: the spawned
agent writes and runs the script, iterates on failures, and returns only the
outcome, so exploration noise (schema dumps, tracebacks, partial prints) never
lands in your context. Spawn one when the scripting itself will take iteration
or the data is large; keep only trivial one-shot scripts inline.

## Rules for the script itself

1. **Shapes first, never guessed.** Before consuming fields of a tool's output,
   check its return shape: `schema("TOOL_NAME")` in the script (cached at
   `/workspace/.gaia/tools/TOOL_NAME.json`), or `get_tool_schema` before writing
   the script. A guessed field name costs a full failed run.
2. **ONE script.** Fetch, filter/compute, act, then print a concise summary.
   Splitting into several bash runs re-fetches everything (each run is a fresh
   process) and burns the per-run call budget.
3. **Batch, don't loop one-at-a-time.** Prefer the tool's own batch/max_results
   parameters over per-item calls; calls are budgeted per bash run.
4. **Side effects are not retries.** Before re-running a script that sends,
   creates, or deletes, confirm what already happened — verify-then-redo is how
   double-sends occur. Make the acting step idempotent (check before write) when
   possible.
5. **Print little.** stdout returns to the model: print counts, ids, and
   outcomes, never raw payloads. Keep large data in variables or files.
6. **Fail loud and read the error.** `GaiaToolError` carries exact validation
   errors; fix `data` and rerun once. Never retry an identical failing call.
