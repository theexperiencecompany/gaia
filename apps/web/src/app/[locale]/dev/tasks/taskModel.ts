/**
 * Demo shape of the unified task. Every field maps to a real todo or workflow field;
 * the comment names it, so the design never shows something the backend can't produce.
 */

import type { Priority, SubTask } from "@/types/features/todoTypes";

export type Assignee = "you" | "gaia";

export type WhenKind = "anytime" | "at" | "schedule" | "event" | "watch";

/** An event's own settings: trigger_config.trigger_data, by the trigger schema's keys. */
export type TriggerData = Record<string, string | string[] | number | boolean>;

/** When a repeating task stops on its own: max_occurrences or stop_after (yyyy-MM-dd). */
export interface TaskEnds {
  afterRuns?: number;
  onDate?: string;
}

/** when.watch.template: the typed kinds a watch compiles to; there are no free-form operators. */
export type WatchKind =
  | "threshold"
  | "state"
  | "new_items"
  | "reply_by"
  | "uptime"
  | "open";

/** when.watch.source.rung: how GAIA reads the value, cheapest first. */
export type WatchRung =
  | "connector"
  | "api"
  | "feed"
  | "page"
  | "browser"
  | "agent";

/** What GAIA reads: when.watch.source, picked once by the model when the sentence is read. */
export interface WatchSource {
  rung: WatchRung;
  /** A connected app it reads through (connector rung): the integration id, for its logo. */
  app?: string;
  /** The site it reads (api, feed, page, browser): its host, for its icon. */
  site?: string;
  /** The thing on it, as it reads: "Billy bookcase", "AI 101 on Dec 3". */
  label: string;
}

/** when.watch.condition, per template. Amounts are in the source's own unit. */
export interface WatchCondition {
  /** threshold: below or above the value. */
  direction?: "below" | "above";
  value?: number;
  /** threshold: the unit as it reads before the number ("$", "₹") or after it ("°F"). */
  unit?: string;
  /** state: the value it waits for, and the values it can take. */
  target?: string;
  states?: string[];
  /** state: the final values; reaching one ends the watch. */
  finalStates?: string[];
  /** new_items: what counts as a new item, as it reads. */
  items?: string;
  /** reply_by: whose reply, and the deadline (ISO). */
  from?: string;
  deadline?: string;
}

/** Why GAIA can't read the value: when.watch.blind_reason. Each has one suggested fix. */
export type BlindReason = "signed_out" | "blocked" | "page_changed";

export interface TaskWatch {
  /** when.watch.sentence: the user's words, read once by the model. */
  sentence: string;
  /** when.watch.template. */
  kind: WatchKind;
  source: WatchSource;
  condition: WatchCondition;
  /** when.watch.last_value and last_checked_at (ISO): the latest reading. */
  reading?: { value: string; at: string };
  /** when.watch.cadence_minutes, never under the source's floor. */
  everyMinutes: number;
  /** when.watch.confirm: scraped values and uptime are read twice, a minute apart, before telling you. */
  confirmTwice: boolean;
  /** when.watch.expires_at (ISO): every watch ends by this, 90 days out and renewable. */
  expiresAt: string;
  /** when.watch.blind_reason and blind_since (ISO): unset while GAIA can see it. */
  blind?: { reason: BlindReason; since: string };
  /** when.watch.ended_reason and ended_at (ISO): how it ended, in a line. */
  ended?: { why: string; at: string };
  /** when.watch.alert_count: times it has told you, read against ends.afterRuns. */
  alerts: number;
}

/** How a webhook's deliveries are verified: subscriptions[].signature. */
export type WebhookSigning = "none" | "secret" | "stripe" | "github";

export interface TaskWebhook {
  /** subscriptions[].webhook_id: the random, rotatable part of the task's URL. */
  id: string;
  signing: WebhookSigning;
  /** subscriptions[].secret: shown once, when the signing that needs it is chosen. */
  secret?: string;
  /** subscriptions[].last_received_at (ISO), after the first delivery. */
  lastReceived?: string;
}

export interface TaskWhen {
  kind: WhenKind;
  /** How it reads in one short line; built from the fields below by whenModel. */
  label?: string;
  /** The full schedule in words, where the short label had to fall back to a generic one. */
  detail?: string;
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
  /** Event: the task's own webhook, when trigger is WEBHOOK_TRIGGER. */
  webhook?: TaskWebhook;
  /** Watch: when.watch, the change GAIA checks for. */
  watch?: TaskWatch;
  /** Schedule, event or watch: max_occurrences / stop_after. */
  ends?: TaskEnds;
}

/**
 * What blocks GAIA on the user. Two real mechanisms:
 * approval: a pending HIL ledger row (todo.pending_approval), approve or deny.
 * question: waiting_on="user" with todo.question; answered by replying in chat.
 * A lost or missing app is not an ask: it is pause_reason plus the missing app (see Task).
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
export type Need = TaskAsk["kind"] | "reconnect" | "connect" | "blind";

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
  /** trigger_type: manual, schedule, watch, webhook, or the app whose event started it. */
  trigger: "manual" | "schedule" | "watch" | "webhook" | string;
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
  /**
   * pause_reason / deactivated_reason: why the system switched it off; unset when you did.
   * integration_missing: made from a template whose app isn't connected (blocked_on_integrations).
   */
  pauseReason?:
    | "integration_expired"
    | "integration_missing"
    | "user_dormant"
    | "watch_blind";
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

/** Has a single due moment, so priority means something: not a repeat, an event or a watch. */
export function takesPriority(when: TaskWhen): boolean {
  return !isRepeating(when) && when.kind !== "watch";
}

/** What the task needs from you, if anything: its ask, or an app to reconnect. */
export function needOf(task: Task): Need | undefined {
  if (task.state === "done") return undefined;
  if (task.ask) return task.ask.kind;
  if (task.pauseReason === "integration_expired") return "reconnect";
  if (task.pauseReason === "integration_missing") return "connect";
  // A watch that can't see asks for a fix, unless you stopped it yourself.
  const isStopped = task.state === "paused" && !task.pauseReason;
  if (task.when.watch?.blind && !isStopped) return "blind";
  return undefined;
}
