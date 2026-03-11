import { useLocalSearchParams } from "expo-router";
import { useMemo } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { TodoScreen } from "@/features/todos/components/TodoScreen";
import { Priority, type TodoFilters } from "@/features/todos/types";

const PRIORITY_TITLES: Record<string, string> = {
  [Priority.HIGH]: "High Priority",
  [Priority.MEDIUM]: "Medium Priority",
  [Priority.LOW]: "Low Priority",
};

function isPriority(value: string): value is Priority {
  return Object.values(Priority).includes(value as Priority);
}

export default function PriorityTodosScreen() {
  const { priority } = useLocalSearchParams<{ priority: string }>();
  const validPriority = isPriority(priority) ? priority : Priority.HIGH;

  const filters: TodoFilters = useMemo(
    () => ({ priority: validPriority, completed: false }),
    [validPriority],
  );

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <TodoScreen
        title={PRIORITY_TITLES[validPriority] ?? "Priority Todos"}
        filters={filters}
        showPriorityFilters={false}
      />
    </GestureHandlerRootView>
  );
}
