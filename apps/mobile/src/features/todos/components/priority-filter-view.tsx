import { FlashList } from "@shopify/flash-list";
import { useFocusEffect } from "expo-router";
import { useCallback, useRef } from "react";
import { View } from "react-native";
import { AppIcon, Flag02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useConfirmDialog } from "@/shared/components/ui/app-confirm-dialog";
import { todoApi } from "../api/todo-api";
import { useTodos } from "../hooks/use-todos";
import type { Todo, TodoUpdate } from "../types/todo-types";
import type { TodoDetailSheetRef } from "./detail/todo-detail-sheet";
import { TodoDetailSheet } from "./detail/todo-detail-sheet";
import { TodoEmptyState } from "./list/todo-empty-state";
import { TodoListSkeleton } from "./list/todo-list-skeleton";
import { TodoRow } from "./row/todo-row";

const PRIORITY_META: Record<string, { label: string; color: string }> = {
  urgent: { label: "Urgent", color: "#f87171" },
  high: { label: "High", color: "#f87171" },
  medium: { label: "Medium", color: "#facc15" },
  low: { label: "Low", color: "#60a5fa" },
  none: { label: "None", color: "#a1a1aa" },
};

interface PriorityFilterViewProps {
  priority: string;
  onTodoPress?: (todo: Todo) => void;
}

export function PriorityFilterView({
  priority,
  onTodoPress,
}: PriorityFilterViewProps) {
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
  } = useTodos({ priority });

  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  const meta = PRIORITY_META[priority.toLowerCase()] ?? {
    label: priority,
    color: "#a1a1aa",
  };

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

  return (
    <View style={{ flex: 1, backgroundColor: "#0a0a0a" }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingHorizontal: 16,
          paddingVertical: 10,
          backgroundColor: "rgba(39,39,42,0.30)",
        }}
      >
        <AppIcon icon={Flag02Icon} size={14} color={meta.color} />
        <Text style={{ fontSize: 13, fontWeight: "600", color: meta.color }}>
          {meta.label} priority
        </Text>
        {todos.length > 0 ? (
          <View
            style={{
              backgroundColor: "rgba(39,39,42,0.60)",
              borderRadius: 999,
              paddingHorizontal: 8,
              paddingVertical: 1,
              marginLeft: "auto",
            }}
          >
            <Text style={{ fontSize: 11, color: "#a1a1aa", fontWeight: "600" }}>
              {todos.length}
            </Text>
          </View>
        ) : null}
      </View>

      {isLoading && todos.length === 0 ? (
        <TodoListSkeleton />
      ) : todos.length === 0 ? (
        <TodoEmptyState filter="all" />
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
