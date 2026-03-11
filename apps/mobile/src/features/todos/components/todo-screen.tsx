import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Add01Icon, ArrowLeft01Icon, AppIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { useTodos } from "../hooks/use-todos";
import type { TodoCreate } from "../types/todo-types";
import { CreateTodoModal } from "./create-todo-modal";
import { TodoFilters } from "./todo-filters";
import { TodoList } from "./todo-list";

export function TodoScreen() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const [showCreate, setShowCreate] = useState(false);

  const {
    todos,
    projects,
    counts,
    isLoading,
    isRefreshing,
    error,
    activeFilter,
    setActiveFilter,
    refetch,
    createTodo,
    toggleComplete,
    deleteTodo,
  } = useTodos();

  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  const handleCreated = async (data: TodoCreate) => {
    try {
      await createTodo(data);
      setShowCreate(false);
    } catch {
      // error is handled in the hook
    }
  };

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

        <Text
          style={{
            marginLeft: spacing.md,
            fontSize: fontSize.lg,
            fontWeight: "600",
            color: "#f4f4f5",
            flex: 1,
          }}
        >
          Todos
        </Text>

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

      {/* Filter tabs */}
      <TodoFilters
        activeFilter={activeFilter}
        onFilterChange={setActiveFilter}
        counts={counts}
      />

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
            onPress={() => {
              void refetch();
            }}
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
          projects={projects}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          onRefresh={() => {
            void refetch();
          }}
          onToggleComplete={toggleComplete}
          onDeleteTodo={(id) => {
            void deleteTodo(id);
          }}
        />
      )}

      <CreateTodoModal
        visible={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={handleCreated}
      />
    </View>
  );
}
