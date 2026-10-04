---
name: gaia-delegate-long-work
description: Delegate long-running sandbox work to a tracked todo that the run itself wakes. Read before starting any task that outlives this turn.
target: executor
---

# Delegating Long-Running Work to a Tracked Todo

You do not supervise long work. The todo does. Your job is bootstrap + handoff, then you finish.

## Rule

One-shot commands run direct. Anything an LLM runs (Claude Code, OpenCode), or anything someone may need to observe or steer after this turn, belongs on a tracked todo.

## Bootstrap (the only active turn)

1. `create_tracked_todo` with the goal and done-checks on the canvas, and a recurrence as the safety net (every 30-60 minutes while the run is live).
2. Launch with `bash(command, background=True, run_todo_id=<todo>)`. Never foreground; it dies with your turn. Passing the todo id subscribes the todo to the run: every event the agent reports (finished, needs input, error) runs the todo with that event attached. The tool also injects the run env (`GAIA_LAB_*`, `OPENCODE_CONFIG_DIR`). Run the CLI in the user's repo; see `claude-code-run-task` / `opencode-run-task` for the launch line.
3. Write the returned pid, log path and run workdir on the todo's canvas. A later run starts in a fresh conversation and only finds the log through the canvas.
4. Tell the user it is underway, in plain words, and FINISH.

## When the todo runs

- **Woken by a run event.** The prompt carries the agent's raw hook payload. Tail the log, then: relay a question to the user, report and complete on done, resume with a nudge if it stopped short, or say what failed. Every resume is `bash(..., background=True)`: record its new log path on the canvas, then finish the turn; the resumed agent's next event wakes the todo again.
- **Woken by its schedule (no event).** Check the pid and the log's age. Alive and moving: stay silent. Dead with the goal unmet: resume once; if that fails, mark it failed and tell the user with the last output.

## Steering from any surface

To answer "how is it going", read the canvas and tail the log. To pass the user's answer on, note it on the canvas, then source the run's lab-env and resume the agent's session in the background (claude-code-run-task / opencode-run-task), and finish. If the resume fails, say so.

## Transparency

Every state change lands in activity with timestamp and actor: the watch starting, every event, every question and answer, resumes, failures, completion. Nothing about a run lives only in a chat transcript. Never show the user run ids, session ids or tokens.
