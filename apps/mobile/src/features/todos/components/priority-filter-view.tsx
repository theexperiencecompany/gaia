import { useFocusEffect } from "expo-router";
import { useCallback } from "react";
import { View } from "react-native";
import { AppIcon, Flag02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { useTodos } from "../hooks/use-todos";
import type { Todo } from "../types/todo-types";
import { TodoList } from "./todo-list";

const PRIORITY_META: Record<
  string,
  { label: string; color: string; emoji: string }
> = {
  urgent: { label: "Urgent", color: "#ef4444", emoji: "🔴" },
  high: { label: "High", color: "#ef4444", emoji: "🔴" },
  medium: { label: "Medium", color: "#f97316", emoji: "🟠" },
  low: { label: "Low", color: "#eab308", emoji: "🟡" },
  none: { label: "None", color: "#71717a", emoji: "🟢" },
};

interface PriorityFilterViewProps {
  priority: string;
  onTodoPress?: (todo: Todo) => void;
}

export function PriorityFilterView({
  priority,
  onTodoPress,
}: PriorityFilterViewProps) {
  const { spacing, fontSize } = useResponsive();

  const {
    todos,
    projects,
    isLoading,
    isRefreshing,
    refetch,
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
    color: "#71717a",
    emoji: "⚪",
  };

  return (
    <View style={{ flex: 1, backgroundColor: "#131416" }}>
      {/* Priority header banner */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm + 2,
          backgroundColor: `${meta.color}12`,
          borderBottomWidth: 1,
          borderBottomColor: `${meta.color}20`,
        }}
      >
        <AppIcon icon={Flag02Icon} size={15} color={meta.color} />
        <Text
          style={{
            fontSize: fontSize.sm,
            fontWeight: "600",
            color: meta.color,
          }}
        >
          {meta.label} Priority
        </Text>
        {todos.length > 0 && (
          <View
            style={{
              backgroundColor: `${meta.color}20`,
              borderRadius: 999,
              paddingHorizontal: 8,
              paddingVertical: 2,
              marginLeft: "auto",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                fontWeight: "600",
                color: meta.color,
              }}
            >
              {todos.length}
            </Text>
          </View>
        )}
      </View>

      {todos.length === 0 && !isLoading ? (
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: 32,
            gap: 8,
          }}
        >
          <Text style={{ fontSize: 36 }}>{meta.emoji}</Text>
          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "600",
              color: "#71717a",
              textAlign: "center",
            }}
          >
            No {meta.label.toLowerCase()} priority tasks
          </Text>
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#52525b",
              textAlign: "center",
            }}
          >
            Tasks with {meta.label.toLowerCase()} priority will appear here.
          </Text>
        </View>
      ) : (
        <TodoList
          todos={todos}
          projects={projects}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          onRefresh={() => void refetch()}
          onToggleComplete={toggleComplete}
          onTodoPress={onTodoPress}
          onDeleteTodo={(id) => void deleteTodo(id)}
          selectionMode={false}
          selectedIds={new Set()}
          onEnterSelectionMode={() => undefined}
          onSelectTodo={() => undefined}
        />
      )}
    </View>
  );
}
