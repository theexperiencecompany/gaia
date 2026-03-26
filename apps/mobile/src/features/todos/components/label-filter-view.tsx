import { useFocusEffect } from "expo-router";
import { useCallback } from "react";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { useTodos } from "../hooks/use-todos";
import type { Todo } from "../types/todo-types";
import { TodoList } from "./todo-list";

interface LabelFilterViewProps {
  label: string;
  onTodoPress?: (todo: Todo) => void;
}

export function LabelFilterView({ label, onTodoPress }: LabelFilterViewProps) {
  const { fontSize } = useResponsive();

  const {
    todos,
    projects,
    isLoading,
    isRefreshing,
    refetch,
    toggleComplete,
    deleteTodo,
  } = useTodos({ label });

  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  return (
    <View style={{ flex: 1, backgroundColor: "#131416" }}>
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
          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "600",
              color: "#71717a",
              textAlign: "center",
            }}
          >
            No todos with label "{label}"
          </Text>
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#52525b",
              textAlign: "center",
            }}
          >
            Add this label to a todo from its detail sheet.
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
