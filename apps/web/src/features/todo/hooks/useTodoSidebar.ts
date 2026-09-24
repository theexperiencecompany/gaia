import type {
  Priority,
  SubTask,
  Todo,
  TodoUpdate,
} from "@/types/features/todoTypes";

interface UseTodoSidebarArgs {
  todo: Todo | null;
  onUpdate: (todoId: string, updates: TodoUpdate) => void;
  onDelete: (todoId: string) => void;
}

/** The todo sidebar's writes; each is a no-op without a todo. */
export function useTodoSidebar({
  todo,
  onUpdate,
  onDelete,
}: UseTodoSidebarArgs) {
  const update = (updates: TodoUpdate) => {
    if (todo) onUpdate(todo.id, updates);
  };

  return {
    handleToggleComplete: () => update({ completed: !todo?.completed }),
    handleDelete: () => {
      if (todo) onDelete(todo.id);
    },
    handleSubtasksChange: (subtasks: SubTask[]) => update({ subtasks }),
    handleTitleSave: (newTitle: string) => {
      const title = newTitle.trim();
      if (title && newTitle !== todo?.title) update({ title });
    },
    handleDescriptionSave: (newDescription: string) => {
      if (newDescription !== todo?.description) {
        update({ description: newDescription });
      }
    },
    handleFieldChange: (
      field: keyof TodoUpdate,
      value: string | string[] | Priority | undefined,
    ) => update({ [field]: value } as TodoUpdate),
    handleWorkflowLinked: (workflowId: string) =>
      update({ workflow_id: workflowId }),
  };
}
