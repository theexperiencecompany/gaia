export enum Priority {
  HIGH = "high",
  MEDIUM = "medium",
  LOW = "low",
  NONE = "none",
}

export interface SubTask {
  id: string;
  title: string;
  completed: boolean;
  created_at: string;
}

/** Who owns getting a todo done. */
export type TodoAssignee = "user" | "gaia";

/** Lifecycle state of a GAIA-assigned todo's execution. */
export type ExecutionStatus =
  | "proposed"
  | "queued"
  | "running"
  | "needs_you"
  | "done"
  | "failed"
  | "expired"
  | "dismissed";

export enum ConditionOperator {
  EQUALS = "equals",
  NOT_EQUALS = "not_equals",
  CONTAINS = "contains",
  NOT_CONTAINS = "not_contains",
  STARTS_WITH = "starts_with",
  ENDS_WITH = "ends_with",
  GREATER_THAN = "greater_than",
  GREATER_OR_EQUAL = "greater_or_equal",
  LESS_THAN = "less_than",
  LESS_OR_EQUAL = "less_or_equal",
}

export enum SubscriptionAction {
  EXECUTE = "execute",
  NOTIFY = "notify",
  COMPLETE = "complete",
  UNBLOCK = "unblock",
}

export enum SubscriptionStatus {
  ACTIVE = "active",
  PAUSED = "paused",
}

/** Whether all of a subscription's conditions must hold (AND) or any one (OR). */
export enum ConditionMatch {
  ALL = "all",
  ANY = "any",
}

/** How dispatch finds a subscription: account-level triggers register no instance id. */
export enum SubscriptionResolution {
  TRIGGER_ID = "trigger_id",
  ACCOUNT = "account",
}

export interface SubscriptionCondition {
  field_name: string;
  operator: ConditionOperator;
  value: string | number;
}

export interface TriggerSubscription {
  id: string;
  trigger_name: string;
  conditions: SubscriptionCondition[];
  match: ConditionMatch;
  action: SubscriptionAction;
  cooldown_seconds: number;
  resolution: SubscriptionResolution;
  composio_trigger_ids: string[];
  status: SubscriptionStatus;
  created_at: string;
}

export interface Todo {
  id: string;
  user_id: string;
  title: string;
  description?: string;
  labels: string[];
  due_date?: string;
  due_date_timezone?: string;
  priority: Priority;
  project_id: string;
  completed: boolean;
  subtasks: SubTask[];
  workflow_id?: string;
  vfs_path?: string;
  scheduled_at?: string | null; // ISO datetime string
  recurrence?: string | null; // 'daily' | 'weekly' | 'every_4h' | cron expression
  expires_at?: string | null; // ISO datetime — when this task becomes irrelevant
  references?: string[]; // IDs of related past tracked todos
  workflow_categories?: string[];
  /** Read-only: written by trigger registration, never by a client payload. */
  trigger_subscriptions?: TriggerSubscription[];
  starred?: boolean;
  created_at: string;
  updated_at: string;
  /** Who this todo is assigned to — a plain user todo or one GAIA proposed/is executing. */
  assignee?: TodoAssignee;
  /** Execution lifecycle state, only meaningful when `assignee === "gaia"`. */
  execution_status?: ExecutionStatus | null;
  /** Human-readable reason GAIA proposed/is executing this todo. */
  serves?: string | null;
  /** Populated when `execution_status === "failed"` — surfaced loudly in the UI. */
  error_message?: string | null;
  /** The decision a `needs_you` run is blocked on; answering re-queues it. */
  blocker_question?: string | null;
  /** Conversation of the most recent execution run — click-through into the chat. */
  last_run_conversation_id?: string | null;
  /** Present on some user-owned todos GAIA is offering to take over. */
  gaia_offer?: string | null;
  /** Set once the user dismisses GAIA's takeover offer — suppresses the affordance. */
  gaia_offer_dismissed?: boolean;
  /** "task" (default) or "goal" — a long-lived lane whose canvas is its strategy. */
  kind?: "task" | "goal";
  /** For a task, the goal-todo it advances. */
  goal_id?: string | null;
}

export interface TodoUpdate {
  title?: string;
  description?: string;
  labels?: string[];
  due_date?: string;
  due_date_timezone?: string;
  priority?: Priority;
  project_id?: string;
  completed?: boolean;
  subtasks?: SubTask[];
  workflow_id?: string;
  scheduled_at?: string | null;
  recurrence?: string | null;
  expires_at?: string | null;
}

export interface TodoFilters {
  project_id?: string;
  completed?: boolean;
  priority?: Priority;
  has_due_date?: boolean;
  overdue?: boolean;
  skip?: number;
  limit?: number;
  labels?: string[];
  due_today?: boolean;
  due_this_week?: boolean;
  due_after?: string;
  due_before?: string;
  search?: string;
  priority_filter?: string;
}

export interface Project {
  id: string;
  user_id: string;
  name: string;
  description?: string;
  color?: string;
  is_default: boolean;
  todo_count: number;
  created_at: string;
  updated_at: string;
}

export interface PaginationMeta {
  total: number;
  page: number;
  per_page: number;
  pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface TodoListResponse {
  data: Todo[];
  meta: PaginationMeta;
}

export enum WorkflowStatus {
  NOT_STARTED = "not_started",
  GENERATING = "generating",
  COMPLETED = "completed",
  FAILED = "failed",
}

export interface TodoCounts {
  inbox: number;
  today: number;
  upcoming: number;
  completed: number;
  overdue: number;
}

export interface TodoCreate {
  title: string;
  description?: string;
  labels?: string[];
  due_date?: string;
  due_date_timezone?: string;
  priority?: Priority;
  project_id?: string;
  subtasks?: SubTask[];
  scheduled_at?: string | null;
  recurrence?: string | null;
}

export interface ProjectCreate {
  name: string;
  description?: string;
  color?: string;
}

export interface ProjectUpdate {
  name?: string;
  description?: string;
  color?: string;
}

export interface BulkMoveRequest {
  todo_ids: string[];
  project_id: string;
}

export interface TodoLabel {
  name: string;
  count: number;
}
