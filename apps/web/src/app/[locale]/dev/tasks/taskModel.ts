/**
 * Demo shape of the unified task. Every field maps to a real todo or workflow field;
 * the comment names it, so the design never shows something the backend can't produce.
 */

import type { Priority, SubTask } from "@/types/features/todoTypes";

export type Assignee = "you" | "gaia";

export type WhenKind = "anytime" | "at" | "schedule" | "event";

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
  /** Event: the workflow gate's condition, "only when ...". */
  condition?: string;
}

/**
 * What blocks GAIA on the user. Three real mechanisms:
 * approval: a pending HIL ledger row (todo.pending_approval), approve or deny.
 * question: waiting_on="user" with a free-text question; answered by replying in chat.
 * reconnect: a paused workflow (deactivated_reason=integration_expired).
 */
export interface TaskAsk {
  kind: "approval" | "question" | "reconnect";
  /** approval: the gated tool call; question: todo.question; reconnect: the pause reason. */
  prompt: string;
  /** approval: what the gated tool call will send (the approval's args_preview). */
  draft?: { to: string; subject: string; body: string };
  /** if_no_reply="proceed" with default_action, as one sentence. */
  ifNoReply?: string;
}

/** waiting_on, for a GAIA task that is not blocked on the user. */
export type WaitingOn = "event" | "time" | "sub_todos";

export type TaskState =
  | "open"
  | "running"
  | "waiting"
  | "scheduled"
  | "standing"
  | "paused"
  | "done";

export interface TaskEvent {
  at: string;
  text: string;
}

export interface TaskRun {
  id: string;
  at: string;
  outcome: "success" | "failed" | "skipped";
  summary: string;
  duration: string;
}

/** todo.external_ref: the Gmail thread or desk a task belongs to. */
export interface TaskSource {
  app: string;
  label: string;
}

export interface Task {
  id: string;
  title: string;
  description?: string;
  assignee: Assignee;
  state: TaskState;
  when: TaskWhen;
  /** Latest line of the activity log, as GAIA wrote it. */
  status?: string;
  waitingOn?: WaitingOn;
  ask?: TaskAsk;
  /** Workflow prompt, or the tracked todo's brief. */
  instructions?: string;
  integrations: string[];
  source?: TaskSource;
  priority: Priority;
  /** GAIA's working document (canvas_content), by its fixed sections. */
  canvas?: { heading: string; body: string }[];
  /** Proposed: ids of the steps GAIA does, on a to-do that is otherwise yours. */
  gaiaSteps?: string[];
  /** Proposed: one thing GAIA offers to do for you on your own to-do. */
  offer?: string;
  /** The task this one is a step of (parent_todo_id). One level deep. */
  parentId?: string;
  /** System workflow, created by GAIA. */
  setUpByGaia?: boolean;
  /** Workflow icon identity. */
  icon?: { name: string; color: string };
  /** Todo subtasks: the checklist, whoever ticks it. */
  checklist: SubTask[];
  activity: TaskEvent[];
  runs: TaskRun[];
  notify: boolean;
  /** completed_at falls on today: stays visible, crossed out, until tomorrow. */
  doneToday?: boolean;
}

export function isRepeating(when: TaskWhen): boolean {
  return when.kind === "schedule" || when.kind === "event";
}
