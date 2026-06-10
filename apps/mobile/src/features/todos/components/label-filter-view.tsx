import { FlashList } from "@shopify/flash-list";
import { useFocusEffect } from "expo-router";
import { useCallback, useRef } from "react";
import { View } from "react-native";
import { useConfirmDialog } from "@/shared/components/ui/app-confirm-dialog";
import { todoApi } from "../api/todo-api";
import { useTodos } from "../hooks/use-todos";
import type { Todo, TodoUpdate } from "../types/todo-types";
import type { TodoDetailSheetRef } from "./detail/todo-detail-sheet";
import { TodoDetailSheet } from "./detail/todo-detail-sheet";
import { TodoEmptyState } from "./list/todo-empty-state";
import { TodoListSkeleton } from "./list/todo-list-skeleton";
import { TodoRow } from "./row/todo-row";

interface LabelFilterViewProps {
  label: string;
  onTodoPress?: (todo: Todo) => void;
}

export function LabelFilterView({ label, onTodoPress }: LabelFilterViewProps) {
  const confirm = useConfirmDialog();
  const detailSheetRef = useRef<TodoDetailSheetRef>(null);

  const {
    todos,
    projects,
    isLoading,
    refetch,
    updateTodo,
    toggleComplete,
    deleteTodo,
  } = useTodos({ label });

  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  const handleTodoPress = useCallback(
    (todo: Todo) => {
      if (onTodoPress) {
        onTodoPress(todo);
        return;
      }
      detailSheetRef.current?.open(todo);
    },
    [onTodoPress],
  );

  const handleUpdate = useCallback(
    async (todoId: string, updates: TodoUpdate) => {
      await updateTodo(todoId, updates);
    },
    [updateTodo],
  );

  const handleAddSubtask = useCallback(
    async (todoId: string, title: string) => {
      await todoApi.addSubtask(todoId, title);
      void refetch();
    },
    [refetch],
  );

  const handleToggleSubtask = useCallback(
    async (todoId: string, subtaskId: string, completed: boolean) => {
      await todoApi.toggleSubtask(todoId, subtaskId, completed);
      void refetch();
    },
    [refetch],
  );

  const handleDeleteSubtask = useCallback(
    async (todoId: string, subtaskId: string) => {
      await todoApi.deleteSubtask(todoId, subtaskId);
      void refetch();
    },
    [refetch],
  );

  const handleDelete = useCallback(
    async (todo: Todo) => {
      const ok = await confirm({
        title: "Delete todo",
        message: `Delete "${todo.title}"?`,
        confirmLabel: "Delete",
        destructive: true,
      });
      if (!ok) return;
      void deleteTodo(todo.id);
    },
    [confirm, deleteTodo],
  );

  const renderItem = useCallback(
    ({ item }: { item: Todo }) => {
      const project = projects.find((p) => p.id === item.project_id);
      return (
        <TodoRow
          todo={item}
          project={project}
          onToggleComplete={toggleComplete}
          onPress={handleTodoPress}
          onDelete={handleDelete}
          onSnooze={() => undefined}
          onLongPress={() => undefined}
          onOpenMenu={() => undefined}
          selectionMode={false}
          isSelected={false}
          onSelect={() => undefined}
        />
      );
    },
    [projects, toggleComplete, handleTodoPress, handleDelete],
  );

  if (isLoading && todos.length === 0) {
    return (
      <View style={{ flex: 1, backgroundColor: "#0a0a0a" }}>
        <TodoListSkeleton />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: "#0a0a0a" }}>
      {todos.length === 0 ? (
        <TodoEmptyState
          filter="all"
          isSearchEmpty={false}
          onAddTodo={undefined}
        />
      ) : (
        <FlashList
          data={todos}
          keyExtractor={(t) => t.id}
          renderItem={renderItem}
          contentContainerStyle={{ paddingTop: 8, paddingBottom: 24 }}
        />
      )}
      <TodoDetailSheet
        ref={detailSheetRef}
        projects={projects}
        onUpdate={handleUpdate}
        onAddSubtask={handleAddSubtask}
        onToggleSubtask={handleToggleSubtask}
        onDeleteSubtask={handleDeleteSubtask}
      />
    </View>
  );
}
