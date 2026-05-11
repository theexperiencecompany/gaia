import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { forwardRef, useCallback, useImperativeHandle, useState } from "react";
import { View } from "react-native";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import type {
  Project,
  SubTask,
  Todo,
  TodoUpdate,
} from "../../types/todo-types";
import { TodoDetailFields } from "./todo-detail-fields";
import { TodoDetailFooter } from "./todo-detail-footer";
import { TodoDetailSubtasks } from "./todo-detail-subtasks";
import { TodoWorkflowSection } from "./todo-workflow-section";

export interface TodoDetailSheetRef {
  open: (todo: Todo) => void;
  close: () => void;
}

interface TodoDetailSheetProps {
  projects: Project[];
  onUpdate: (todoId: string, updates: TodoUpdate) => Promise<void>;
  onDelete?: (todo: Todo) => void;
  onAddSubtask: (todoId: string, title: string) => Promise<void>;
  onToggleSubtask: (
    todoId: string,
    subtaskId: string,
    completed: boolean,
  ) => Promise<void>;
  onDeleteSubtask: (todoId: string, subtaskId: string) => Promise<void>;
}

export const TodoDetailSheet = forwardRef<
  TodoDetailSheetRef,
  TodoDetailSheetProps
>(
  (
    {
      projects,
      onUpdate,
      onDelete,
      onAddSubtask,
      onToggleSubtask,
      onDeleteSubtask,
    },
    ref,
  ) => {
    const [isOpen, setIsOpen] = useState(false);
    const [todo, setTodo] = useState<Todo | null>(null);

    useImperativeHandle(ref, () => ({
      open: (t: Todo) => {
        setTodo(t);
        setIsOpen(true);
      },
      close: () => setIsOpen(false),
    }));

    const handleChange = useCallback(
      (update: TodoUpdate) => {
        if (!todo) return;
        // optimistic local update so the sheet reflects changes immediately
        // even if the parent list query has not refetched yet.
        const localUpdate: Partial<Todo> = {
          ...(update.title !== undefined ? { title: update.title } : {}),
          ...(update.description !== undefined
            ? { description: update.description }
            : {}),
          ...(update.priority !== undefined
            ? { priority: update.priority }
            : {}),
          ...(update.due_date !== undefined
            ? { due_date: update.due_date }
            : {}),
          ...(update.due_date_timezone !== undefined
            ? { due_date_timezone: update.due_date_timezone }
            : {}),
          ...(update.project_id !== undefined
            ? { project_id: update.project_id }
            : {}),
          ...(update.labels !== undefined ? { labels: update.labels } : {}),
          ...(update.recurrence !== undefined
            ? { recurrence: update.recurrence }
            : {}),
          ...(update.completed !== undefined
            ? { completed: update.completed }
            : {}),
        };
        setTodo({ ...todo, ...localUpdate } as Todo);
        // Swallow recurrence-only failures silently — backend may not yet
        // accept the field. Other failures are surfaced by the hook.
        void onUpdate(todo.id, update).catch(() => {
          /* silent rollback for not-yet-shipped endpoints */
        });
      },
      [todo, onUpdate],
    );

    const handleAddSubtask = useCallback(
      async (todoId: string, title: string) => {
        await onAddSubtask(todoId, title);
        setTodo((prev) =>
          prev && prev.id === todoId
            ? {
                ...prev,
                subtasks: [
                  ...prev.subtasks,
                  {
                    id: `optimistic-${Date.now()}`,
                    title,
                    completed: false,
                    created_at: new Date().toISOString(),
                  } satisfies SubTask,
                ],
              }
            : prev,
        );
      },
      [onAddSubtask],
    );

    const handleToggleSubtask = useCallback(
      async (todoId: string, subtaskId: string, completed: boolean) => {
        setTodo((prev) =>
          prev && prev.id === todoId
            ? {
                ...prev,
                subtasks: prev.subtasks.map((s) =>
                  s.id === subtaskId ? { ...s, completed } : s,
                ),
              }
            : prev,
        );
        await onToggleSubtask(todoId, subtaskId, completed);
      },
      [onToggleSubtask],
    );

    const handleDeleteSubtask = useCallback(
      async (todoId: string, subtaskId: string) => {
        setTodo((prev) =>
          prev && prev.id === todoId
            ? {
                ...prev,
                subtasks: prev.subtasks.filter((s) => s.id !== subtaskId),
              }
            : prev,
        );
        await onDeleteSubtask(todoId, subtaskId);
      },
      [onDeleteSubtask],
    );

    const handleToggleComplete = useCallback(() => {
      if (!todo) return;
      const nextCompleted = !todo.completed;
      // Cascade rule: completing the parent cascades to subtasks. The
      // reverse (uncompleting) does not change subtask state.
      const nextSubtasks = nextCompleted
        ? todo.subtasks.map((s) => ({ ...s, completed: true }))
        : todo.subtasks;
      setTodo({
        ...todo,
        completed: nextCompleted,
        subtasks: nextSubtasks,
      });
      void onUpdate(todo.id, {
        completed: nextCompleted,
        ...(nextCompleted && todo.subtasks.length > 0
          ? { subtasks: nextSubtasks }
          : {}),
      }).catch(() => {
        /* hook surfaces error */
      });
    }, [todo, onUpdate]);

    const handleDelete = useCallback(() => {
      if (!todo) return;
      setIsOpen(false);
      onDelete?.(todo);
    }, [todo, onDelete]);

    return (
      <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
        <BottomSheet.Portal>
          <BottomSheet.Overlay />
          <BottomSheet.Content
            snapPoints={["90%"]}
            enableDynamicSizing={false}
            enablePanDownToClose
            backgroundStyle={{ backgroundColor: "#18181b" }}
            handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
          >
            {todo ? (
              <View style={{ flex: 1 }}>
                <BottomSheetScrollView
                  contentContainerStyle={{
                    paddingHorizontal: 20,
                    paddingTop: 8,
                    paddingBottom: 24,
                    gap: 18,
                  }}
                  keyboardShouldPersistTaps="handled"
                >
                  <TodoDetailFields
                    todo={todo}
                    projects={projects}
                    onChange={handleChange}
                  />
                  <TodoDetailSubtasks
                    todoId={todo.id}
                    subtasks={todo.subtasks}
                    onAdd={handleAddSubtask}
                    onToggle={handleToggleSubtask}
                    onDelete={handleDeleteSubtask}
                  />
                  {!todo.id.startsWith("optimistic-") ? (
                    <TodoWorkflowSection todoId={todo.id} />
                  ) : null}
                </BottomSheetScrollView>
                <TodoDetailFooter
                  completed={todo.completed}
                  onToggleComplete={handleToggleComplete}
                  onDelete={handleDelete}
                />
              </View>
            ) : (
              <View />
            )}
          </BottomSheet.Content>
        </BottomSheet.Portal>
      </BottomSheet>
    );
  },
);

TodoDetailSheet.displayName = "TodoDetailSheet";
