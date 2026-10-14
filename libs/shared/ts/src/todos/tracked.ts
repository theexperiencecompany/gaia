import type { Todo } from "../types/todo";

/**
 * A tracked todo is GAIA's working memory: it runs on the agent from its
 * canvas and never has a workflow, so no workflow UI applies to it.
 */
export function isTrackedTodo(todo: Pick<Todo, "vfs_path">): boolean {
  return !!todo.vfs_path;
}
