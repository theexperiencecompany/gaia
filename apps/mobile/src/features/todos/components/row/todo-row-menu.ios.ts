import { ActionSheetIOS } from "react-native";
import type { Todo, TodoRowMenuActions } from "../../types/todo-types";

/** Shows a todo row's overflow menu as the native iOS action sheet. */
export function openTodoRowMenu(todo: Todo, actions: TodoRowMenuActions) {
  ActionSheetIOS.showActionSheetWithOptions(
    {
      options: ["Edit", "Snooze", "Delete", "Cancel"],
      destructiveButtonIndex: 2,
      cancelButtonIndex: 3,
    },
    (idx) => {
      if (idx === 0) actions.onEdit(todo);
      else if (idx === 1) actions.onSnooze(todo);
      else if (idx === 2) actions.onDelete(todo);
    },
  );
}
