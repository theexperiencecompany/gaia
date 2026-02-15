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
}

/**
 * Accumulated todo_progress data on a message, keyed by source agent.
 * Each source replaces its own slice; frontend merges into one flat list.
 */
export type TodoProgressData = Record<string, TodoProgressSnapshot>;
