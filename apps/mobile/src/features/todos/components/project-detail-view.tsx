import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { Alert, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  Add01Icon,
  AppIcon,
  ArrowLeft01Icon,
  Folder02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { todoApi } from "../api/todo-api";
import { useTodos } from "../hooks/use-todos";
import type {
  Project,
  Todo,
  TodoCreate,
  TodoUpdate,
} from "../types/todo-types";
import { CreateTodoModal } from "./create-todo-modal";
import type { TodoDetailSheetRef } from "./todo-detail-sheet";
import { TodoDetailSheet } from "./todo-detail-sheet";
import { TodoList } from "./todo-list";

interface ProjectDetailViewProps {
  project: Project;
  allProjects: Project[];
}

export function ProjectDetailView({
  project,
  allProjects,
}: ProjectDetailViewProps) {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const [showCreate, setShowCreate] = useState(false);
  const detailSheetRef = useRef<TodoDetailSheetRef>(null);

  const {
    todos,
    isLoading,
    isRefreshing,
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

  const handleCreated = async (data: TodoCreate) => {
    try {
      await createTodo({ ...data, project_id: project.id });
      setShowCreate(false);
    } catch {
      // handled in hook
    }
  };

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

  const projectColor = project.color ?? "#71717a";

  return (
    <View style={{ flex: 1, backgroundColor: "#131416" }}>
      {/* Header */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.07)",
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <Pressable
          onPress={() => router.back()}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
          }}
        >
          <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
        </Pressable>

        {/* Project icon */}
        <View
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            backgroundColor: `${projectColor}20`,
            alignItems: "center",
            justifyContent: "center",
            borderWidth: 1,
            borderColor: `${projectColor}35`,
          }}
        >
          <AppIcon icon={Folder02Icon} size={14} color={projectColor} />
        </View>

        <View style={{ flex: 1 }}>
          <Text
            style={{
              fontSize: fontSize.lg,
              fontWeight: "600",
              color: "#f4f4f5",
            }}
          >
            {project.name}
          </Text>
          <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
            {todos.length} {todos.length === 1 ? "task" : "tasks"}
          </Text>
        </View>

        <Pressable
          onPress={() => setShowCreate(true)}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(22,193,255,0.15)",
          }}
        >
          <AppIcon icon={Add01Icon} size={18} color="#16c1ff" />
        </Pressable>
      </View>

      {/* Error state */}
      {error ? (
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: spacing.xl,
            gap: spacing.md,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#ef4444",
              textAlign: "center",
            }}
          >
            {error}
          </Text>
          <Pressable
            onPress={() => void refetch()}
            style={{
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm,
              backgroundColor: "rgba(22,193,255,0.1)",
            }}
          >
            <Text style={{ fontSize: fontSize.sm, color: "#16c1ff" }}>
              Try again
            </Text>
          </Pressable>
        </View>
      ) : (
        <TodoList
          todos={todos}
          projects={allProjects}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          onRefresh={() => void refetch()}
          onToggleComplete={toggleComplete}
          onTodoPress={handleTodoPress}
          onDeleteTodo={(id) => {
            Alert.alert("Delete Task", "Are you sure?", [
              { text: "Cancel", style: "cancel" },
              {
                text: "Delete",
                style: "destructive",
                onPress: () => void deleteTodo(id),
              },
            ]);
          }}
        />
      )}

      <CreateTodoModal
        visible={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={handleCreated}
        projects={allProjects}
        defaultProjectId={project.id}
      />

      <TodoDetailSheet
        ref={detailSheetRef}
        projects={allProjects}
        onUpdate={handleUpdate}
        onAddSubtask={handleAddSubtask}
        onToggleSubtask={handleToggleSubtask}
        onDeleteSubtask={handleDeleteSubtask}
      />
    </View>
  );
}
