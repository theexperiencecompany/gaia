---
name: lab-delegate-run
description: Delegate long-running sandbox work to a tracked todo that supervises itself. Read before starting any task that outlives this turn.
target: executor
---

# Delegating Long-Running Work to a Tracked Todo

You do not supervise long work. The todo does. Your job is bootstrap + handoff, then you finish.

## Rule

If anyone will need to observe or steer this after this turn ends, it belongs on a tracked todo. Otherwise run it in background and forget it.

## Bootstrap (first and only active run)

1. `create_tracked_todo` with goal + done-checks on canvas. Recurrence = check interval (e.g. hourly for active builds, daily for slow burns).
2. Seed the run workdir in the sandbox (see `lab-claude-drive` / `lab-opencode-drive` for CLI specifics): credential links, install-if-missing, event egress (hooks fragment or plugin), run id.
3. Launch the command detached (`nohup … >> run.log 2>&1 &` — never foreground; foreground dies with your run). Record pid + log path + run id in `references` (`lab:<run>:<session>`).
4. Post a started line to activity. Report "working on it" and FINISH. You are done; the todo owns it from here.

## What the todo does on each scheduled fire (not you, the recurrence)

Each fire is a fresh worker run on this todo. It reads canvas + activity tail + log tail (`tail -c`, `stat`, exit markers), then exactly one of:

- New output → update canvas status block, append activity. Stay silent.
- Question / done / failed → deliver to subscribed surfaces, record activity.
- Stale tail + dead process → resume from checkpoint or relaunch, record it.
- Nothing new → silence. Never narrate routine polls.

## Steering from any surface

Read the todo (canvas status + tail) to answer progress. To steer, append instruction to canvas and, if the process needs the input now, write the run's inbox + resume its session (see drive skills). Steering from a surface subscribes it to future pings; reading subscribes nothing.

## Transparency

Every state change lands in activity with timestamp and actor. The user can open the todo and see: started lines, every question asked and answered, resumes, failures, completion. Nothing about a run lives only in a chat transcript.
