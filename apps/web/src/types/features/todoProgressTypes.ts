/**
 * Types for agent todo_progress streaming.
 *
 * These represent the agent's internal task planning progress (todo_tools.py),
 * NOT the user's personal todos (todo_tool.py / TodoSection).
 */

export type TodoProgressStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "cancelled";

export interface TodoProgressItem {
  id: string;
  content: string;
  status: TodoProgressStatus;
}

/** A single snapshot emitted by todo_tools for one source agent. */
export interface TodoProgressSnapshot {
  todos: TodoProgressItem[];
  source: string;
  /**
   * Human-readable name for the source (e.g. a custom MCP integration's
   * display name). Sent by the backend so the UI shows the integration name
   * instead of its raw id. Absent on older persisted messages.
   */
  integration_name?: string;
}

/**
 * Accumulated todo_progress data on a message, keyed by source agent.
 * Each source replaces its own slice; frontend merges into one flat list.
 */
export type TodoProgressData = Record<string, TodoProgressSnapshot>;
