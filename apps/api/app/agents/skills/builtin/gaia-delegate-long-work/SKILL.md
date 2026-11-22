---
name: gaia-delegate-long-work
description: Delegate long-running sandbox work to a GAIA task that the run itself wakes. Read before starting any task that outlives this turn.
target: executor
---

# Delegating Long-Running Work to a GAIA Task

You do not supervise long work. The task does. Your job is bootstrap + handoff, then you finish.

## Rule

One-shot commands run direct. Anything an LLM runs (Claude Code, OpenCode), or anything someone may need to observe or steer after this turn, belongs on a GAIA task.

## Bootstrap (the only active turn)

1. `create_task` with `assignee='gaia'`, the goal in `body`, the done-checks in `done_when`, and `waiting_on='event'` with a `next_check` of 30-60 minutes as the safety net: the run's events wake the task, and the check only comes up if none did. Put the standing request in `notes` under "## Standing rules": "Tell the user whenever the agent asks something, finishes, or fails." Delivery always sends results the user asked to hear every time, and Standing rules is where it looks.
2. Launch with `bash(command, background=True, run_task_id=<task id>)`. Never foreground; it dies with your turn. Passing the task id subscribes the task to the run: every event the agent reports (finished, needs input, error) runs the task with that event attached. The tool also injects the run env (`GAIA_LAB_*`, `OPENCODE_CONFIG_DIR`). Run the CLI from the project's folder under `~/agents/work/` (local disk, outside `/workspace`: read it with bash; saved to an archive with every event); see `claude-code-run-task` / `opencode-run-task` for the launch line.
3. Write the returned pid, log path and run workdir in the task's notes (`update_task` notes, under "## Key Details"). A later run starts in the task's own chat and only finds the log through the notes.
4. Tell the user it is underway, in plain words, and FINISH.

## When the task runs

- **Woken by a run event.** The prompt carries the agent's raw hook payload, or GAIA's own `sandbox_replaced` / `save_failed` about the sandbox. Tail the log, then: relay a question to the user, report and `complete_task` on done, resume with a nudge if it stopped short, say what failed, or after `sandbox_replaced` relaunch with `run_task_id` and resume the session by id. Every resume is `bash(..., background=True)`: record its new log path in the notes, then finish the turn; the resumed agent's next event wakes the task again.
- **Woken by its check (no event).** Check the pid and the log's age. Alive and moving: give it a new `next_check` and stay silent. Dead with the goal unmet: resume once; if that fails, tell the user with the last output and close the task.

## Steering from any surface

To answer "how is it going", read the task's notes and tail the log. To pass the user's answer on, note it in the notes, then source the run's lab-env and resume the agent's session in the background (claude-code-run-task / opencode-run-task), and finish. If the resume fails, say so.

## Transparency

Every state change is on the task: the watch starting and every sandbox event land in its log, and every question and answer, resume, failure and completion goes in its notes or its run reports. Nothing about a run lives only in a chat transcript. Never show the user run ids, session ids or tokens.
