/**
 * Demo shape of the unified task. Every field maps to a real todo or workflow field;
 * the comment names it, so the design never shows something the backend can't produce.
 */

import type { Priority, SubTask } from "@/types/features/todoTypes";

export type Assignee = "you" | "gaia";

export type WhenKind = "anytime" | "at" | "schedule" | "event";

/** An event's own settings: trigger_config.trigger_data, by the trigger schema's keys. */
export type TriggerData = Record<string, string | string[] | number | boolean>;

/** When a repeating task stops on its own: max_occurrences or stop_after (yyyy-MM-dd). */
export interface TaskEnds {
  afterRuns?: number;
  onDate?: string;
}

export interface TaskWhen {
  kind: WhenKind;
  /** How it reads in one short line; built from the fields below by whenModel. */
  label?: string;
  overdue?: boolean;
  isToday?: boolean;
  /** Days from today until it is due or next runs; drives soonest-first order. */
  order?: number;
  /** At: todo due_date or workflow scheduled_at, as yyyy-MM-dd, and an optional HH:mm. */
  date?: string;
  time?: string;
  /** Schedule: trigger_config.cron_expression and timezone. */
  cron?: string;
  timezone?: string;
  /** Event: trigger_config.trigger_name, and the app whose trigger it is. */
  trigger?: string;
  app?: string;
  /** Event: trigger_config.trigger_data, the chosen event's settings. */
  triggerData?: TriggerData;
  /** Event: the workflow gate's condition, "only when ...". */
  condition?: string;
  /** Schedule or event: max_occurrences / stop_after. */
  ends?: TaskEnds;
}

/**
 * What blocks GAIA on the user. Two real mechanisms:
 * approval: a pending HIL ledger row (todo.pending_approval), approve or deny.
 * question: waiting_on="user" with todo.question; answered by replying in chat.
 * A lost connection is not an ask: it is pause_reason plus the missing app (see Task).
 */
export interface TaskAsk {
  kind: "approval" | "question";
  /** approval: the gated tool call; question: todo.question. */
  prompt: string;
  /** approval: what the gated tool call will send (the approval's args_preview). */
  draft?: { to: string; subject: string; body: string };
  /** question: todo.if_no_reply, and default_action when the plan is "proceed". */
  ifNoReply?: {
    plan: "ask_again" | "proceed" | "hold";
    defaultAction?: string;
  };
}

/** What a task needs from you, in the list's words. */
export type Need = TaskAsk["kind"] | "reconnect";

/** todo.waiting_on, for a one-off GAIA task between runs. */
export type WaitingOn = "time" | "event" | "user" | "sub_todos" | "unplanned";

export type TaskState =
  | "open"
  | "running"
  | "waiting"
  | "scheduled"
  | "standing"
  | "paused"
  | "done";

/** One call GAIA made in a run: task_runs.trace[], its tool_category and result_digest. */
export interface RunCall {
  app: string;
  text: string;
}

/** A task_runs record (from workflow_executions). */
export interface TaskRun {
  id: string;
  /** started_at, as it reads. */
  at: string;
  /** status. */
  outcome: "success" | "failed" | "skipped";
  summary: string;
  /** duration_seconds, as it reads. */
  duration: string;
  /** trigger_type: manual, schedule, or the app whose event started it. */
  trigger: "manual" | "schedule" | string;
  trace: RunCall[];
  /** error_message, on a failed run. */
  error?: string;
}

/** todo.external_ref: the Gmail thread or desk a task belongs to. */
export interface TaskSource {
  app: string;
  label: string;
}

/**
 * A task GAIA set up itself: source_integration, and why it exists, which is the
 * system definition's description (system_workflow_key; the Inbox desk is the
 * todo whose external_ref.source is inbox_desk).
 */
export interface TaskOrigin {
  app: string;
  why: string;
}

export interface Task {
  id: string;
  title: string;
  description?: string;
  assignee: Assignee;
  state: TaskState;
  when: TaskWhen;
  /** Latest line of the run log, as GAIA wrote it. */
  status?: string;
  waitingOn?: WaitingOn;
  /** scheduled_at while it waits: the next check, or when a question expires (ISO). */
  nextCheck?: string;
  ask?: TaskAsk;
  /** Workflow prompt, or the tracked todo's brief. */
  instructions?: string;
  /** integration_ids: the apps GAIA uses for this task. */
  integrations: string[];
  /** missing_integrations / blocked_on_integrations: those not connected right now. */
  disconnected?: string[];
  /** pause_reason / deactivated_reason: why the system switched it off; unset when you did. */
  pauseReason?: "integration_expired" | "user_dormant";
  source?: TaskSource;
  priority: Priority;
  /** GAIA's working document (canvas_content), by its fixed sections. */
  canvas?: { heading: string; body: string }[];
  /** Proposed: one thing GAIA offers to do for you on your own to-do. */
  offer?: string;
  /** The task this one is a subtask of (parent_id). One level deep. */
  parentId?: string;
  origin?: TaskOrigin;
  /** Workflow icon identity. */
  icon?: { name: string; color: string };
  /** Todo subtasks: the checklist, whoever ticks it. */
  checklist: SubTask[];
  runs: TaskRun[];
  /** occurrence_count: runs so far, read against ends.afterRuns. */
  runCount?: number;
  notify: boolean;
  /** completed_at falls on today: stays visible, crossed out, until tomorrow. */
  doneToday?: boolean;
}

export function isRepeating(when: TaskWhen): boolean {
  return when.kind === "schedule" || when.kind === "event";
}

/** What the task needs from you, if anything: its ask, or an app to reconnect. */
export function needOf(task: Task): Need | undefined {
  if (task.state === "done") return undefined;
  if (task.ask) return task.ask.kind;
  if (task.pauseReason === "integration_expired") return "reconnect";
  return undefined;
}
