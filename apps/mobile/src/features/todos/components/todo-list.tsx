import { useCallback } from "react";
import { FlatList, RefreshControl, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppIcon, CheckmarkCircle02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Project, Todo } from "../types/todo-types";
import { TodoItem } from "./todo-item";

interface TodoListProps {
  todos: Todo[];
  projects: Project[];
  isLoading: boolean;
  isRefreshing: boolean;
  onRefresh: () => void;
  onToggleComplete: (todo: Todo) => void;
  onTodoPress?: (todo: Todo) => void;
  onDeleteTodo?: (todoId: string) => void;
  selectionMode?: boolean;
  selectedIds?: Set<string>;
  onEnterSelectionMode?: (todo: Todo) => void;
  onSelectTodo?: (id: string) => void;
}

function TodoSkeleton() {
  const { spacing } = useResponsive();
  return (
    <View>
      {Array.from({ length: 7 }).map((_, i) => {
        const skeletonKey = `skeleton-${i}`;
        return (
          <View
            key={skeletonKey}
            style={{
              flexDirection: "row",
              alignItems: "flex-start",
              paddingVertical: spacing.md,
              paddingHorizontal: spacing.md,
              borderBottomWidth: 1,
              borderBottomColor: "rgba(255,255,255,0.04)",
            }}
          >
            <View
              style={{
                width: 22,
                height: 22,
                borderRadius: 11,
                backgroundColor: "rgba(255,255,255,0.06)",
                marginTop: 2,
                marginRight: spacing.sm + 4,
                flexShrink: 0,
              }}
            />
            <View style={{ flex: 1, gap: 8 }}>
              <View
                style={{
                  height: 15,
                  borderRadius: 6,
                  backgroundColor: "rgba(255,255,255,0.06)",
                  width: `${55 + (i % 4) * 11}%`,
                }}
              />
              {i % 2 === 0 && (
                <View style={{ flexDirection: "row", gap: 5 }}>
                  <View
                    style={{
                      height: 22,
                      width: 70,
                      borderRadius: 6,
                      backgroundColor: "rgba(255,255,255,0.04)",
                    }}
                  />
                  <View
                    style={{
                      height: 22,
                      width: 52,
                      borderRadius: 6,
                      backgroundColor: "rgba(255,255,255,0.04)",
                    }}
                  />
                </View>
              )}
            </View>
          </View>
        );
      })}
    </View>
  );
}

export function TodoList({
  todos,
  projects,
  isLoading,
  isRefreshing,
  onRefresh,
  onToggleComplete,
  onTodoPress,
  onDeleteTodo,
  selectionMode = false,
  selectedIds,
  onEnterSelectionMode,
  onSelectTodo,
}: TodoListProps) {
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();

  const handleLongPress = useCallback(
    (todo: Todo) => {
      if (!selectionMode) {
        onEnterSelectionMode?.(todo);
      }
    },
    [selectionMode, onEnterSelectionMode],
  );

  const renderItem = useCallback(
    ({ item }: { item: Todo }) => (
      <TodoItem
        todo={item}
        projects={projects}
        onToggleComplete={onToggleComplete}
        onPress={selectionMode ? undefined : onTodoPress}
        onDelete={selectionMode ? undefined : onDeleteTodo}
        selectionMode={selectionMode}
        isSelected={selectedIds?.has(item.id) ?? false}
        onSelect={onSelectTodo}
        onLongPress={handleLongPress}
      />
    ),
    [
      projects,
      onToggleComplete,
      onTodoPress,
      onDeleteTodo,
      selectionMode,
      selectedIds,
      onSelectTodo,
      handleLongPress,
    ],
  );

  const keyExtractor = useCallback((item: Todo) => item.id, []);

  if (isLoading) {
    return <TodoSkeleton />;
  }

  return (
    <FlatList
      data={todos}
      keyExtractor={keyExtractor}
      renderItem={renderItem}
      contentContainerStyle={{
        flexGrow: 1,
        paddingBottom: selectionMode
          ? insets.bottom + 96
          : insets.bottom + spacing.lg,
      }}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={onRefresh}
          tintColor="#16c1ff"
        />
      }
      ListEmptyComponent={
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingVertical: spacing.xl * 3,
            gap: spacing.md,
          }}
        >
          <View
            style={{
              width: 72,
              height: 72,
              borderRadius: 36,
              backgroundColor: "rgba(255,255,255,0.04)",
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.06)",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AppIcon icon={CheckmarkCircle02Icon} size={36} color="#3f3f46" />
          </View>
          <View style={{ alignItems: "center", gap: 6 }}>
            <Text
              style={{
                fontSize: fontSize.base,
                fontWeight: "600",
                color: "#d4d4d8",
                textAlign: "center",
              }}
            >
              No tasks found
            </Text>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#71717a",
                textAlign: "center",
                maxWidth: 240,
              }}
            >
              Create a new task to get started
            </Text>
          </View>
        </View>
      }
    />
  );
}
