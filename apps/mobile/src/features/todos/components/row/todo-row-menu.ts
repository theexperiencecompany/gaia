import type { Todo, TodoRowMenuActions } from "../../types/todo-types";

/** Opens a todo row's overflow menu in-app; iOS shows a native action sheet instead. */
export function openTodoRowMenu(todo: Todo, actions: TodoRowMenuActions) {
  actions.onOpenMenu(todo);
}
