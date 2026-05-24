import { FlashList } from "@shopify/flash-list";
import { useFocusEffect } from "expo-router";
import { useCallback, useRef } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Add01Icon, AppIcon, Folder02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useConfirmDialog } from "@/shared/components/ui/app-confirm-dialog";
import { BackButton } from "@/shared/components/ui/back-button";
import { todoApi } from "../api/todo-api";
import { useTodos } from "../hooks/use-todos";
import type {
  Project,
  Todo,
  TodoCreate,
  TodoUpdate,
} from "../types/todo-types";
import {
  TodoCreateSheet,
  type TodoCreateSheetRef,
} from "./create/todo-create-sheet";
import type { TodoDetailSheetRef } from "./detail/todo-detail-sheet";
import { TodoDetailSheet } from "./detail/todo-detail-sheet";
import { TodoEmptyState } from "./list/todo-empty-state";
import { TodoListSkeleton } from "./list/todo-list-skeleton";
import { TodoRow } from "./row/todo-row";

interface ProjectDetailViewProps {
  project: Project;
  allProjects: Project[];
}

export function ProjectDetailView({
  project,
  allProjects,
}: ProjectDetailViewProps) {
  const insets = useSafeAreaInsets();
  const confirm = useConfirmDialog();
  const detailSheetRef = useRef<TodoDetailSheetRef>(null);
  const createSheetRef = useRef<TodoCreateSheetRef>(null);

  const {
    todos,
    isLoading,
    error,
    refetch,
    createTodo,
    updateTodo,
    toggleComplete,
    deleteTodo,
  } = useTodos({ projectId: project.id });

  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  const handleCreated = useCallback(
    async (data: TodoCreate) => {
      try {
        await createTodo({ ...data, project_id: project.id });
      } catch {
        // handled in hook
      }
    },
    [createTodo, project.id],
  );

  const handleTodoPress = useCallback((todo: Todo) => {
    detailSheetRef.current?.open(todo);
  }, []);

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

  const projectColor = project.color ?? "#a1a1aa";

  const renderItem = useCallback(
    ({ item }: { item: Todo }) => (
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
    ),
    [project, toggleComplete, handleTodoPress, handleDelete],
  );

  return (
    <View style={{ flex: 1, backgroundColor: "#0a0a0a" }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingTop: insets.top + 6,
          paddingHorizontal: 16,
          paddingBottom: 12,
        }}
      >
        <BackButton />
        <View
          style={{
            width: 32,
            height: 32,
            borderRadius: 10,
            backgroundColor: "rgba(39,39,42,0.60)",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <AppIcon icon={Folder02Icon} size={14} color={projectColor} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: 17, fontWeight: "600", color: "#fafafa" }}>
            {project.name}
          </Text>
          <Text style={{ fontSize: 11, color: "#71717a" }}>
            {todos.length} {todos.length === 1 ? "todo" : "todos"}
          </Text>
        </View>
        <Pressable
          onPress={() => createSheetRef.current?.open()}
          hitSlop={8}
          accessibilityLabel="Add todo"
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "#00bbff",
          }}
        >
          <AppIcon icon={Add01Icon} size={18} color="#0a0a0a" />
        </Pressable>
      </View>

      {error ? (
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: 32,
            gap: 12,
          }}
        >
          <Text style={{ fontSize: 14, color: "#fca5a5", textAlign: "center" }}>
            {error}
          </Text>
          <Pressable
            onPress={() => void refetch()}
            style={{
              borderRadius: 10,
              paddingHorizontal: 14,
              paddingVertical: 10,
              backgroundColor: "rgba(0,187,255,0.15)",
            }}
          >
            <Text style={{ fontSize: 13, color: "#00bbff", fontWeight: "600" }}>
              Try again
            </Text>
          </Pressable>
        </View>
      ) : isLoading && todos.length === 0 ? (
        <TodoListSkeleton />
      ) : todos.length === 0 ? (
        <TodoEmptyState
          filter="all"
          onAddTodo={() => createSheetRef.current?.open()}
        />
      ) : (
        <FlashList
          data={todos}
          keyExtractor={(t) => t.id}
          renderItem={renderItem}
          contentContainerStyle={{ paddingTop: 8, paddingBottom: 24 }}
        />
      )}

      <TodoCreateSheet
        ref={createSheetRef}
        projects={allProjects}
        defaultProjectId={project.id}
        onCreated={handleCreated}
      />

      <TodoDetailSheet
        ref={detailSheetRef}
        projects={allProjects}
        onUpdate={handleUpdate}
        onDelete={handleDelete}
        onAddSubtask={handleAddSubtask}
        onToggleSubtask={handleToggleSubtask}
        onDeleteSubtask={handleDeleteSubtask}
      />
    </View>
  );
}
