import type {
  Priority as PriorityLiteral,
  SubTaskOutput,
  TodoModel,
  TodoResponse,
  TodoUpdateRequest,
} from "../api/generated";

export type {
  BulkMoveRequest,
  PaginationMeta,
  ProjectCreate,
  SubscriptionCondition,
  TodoCounts,
  TodoListResponse,
  TriggerSubscription,
} from "../api/generated";

export type Priority = PriorityLiteral;

/** Runtime handles for the `Priority` literals (the enum this replaced). */
export const Priority = {
  HIGH: "high",
  MEDIUM: "medium",
  LOW: "low",
  NONE: "none",
} as const satisfies Record<string, PriorityLiteral>;

export type SubTask = SubTaskOutput;

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

export type Todo = TodoResponse;

export type TodoUpdate = TodoUpdateRequest;

export interface TodoFilters {
  project_id?: string;
  completed?: boolean;
  priority?: PriorityLiteral;
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

export enum WorkflowStatus {
  NOT_STARTED = "not_started",
  GENERATING = "generating",
  COMPLETED = "completed",
  FAILED = "failed",
}

export type TodoCreate = TodoModel;

export interface ProjectUpdate {
  name?: string;
  description?: string;
  color?: string;
}

export interface TodoLabel {
  name: string;
  count: number;
}
