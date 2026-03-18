import * as Haptics from "expo-haptics";
import { Checkbox, Chip } from "heroui-native";
import { useCallback, useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { todoApi } from "@/features/todos/api/todo-api";
import { Priority, type Todo } from "@/features/todos/types/todo-types";
import { useResponsive } from "@/lib/responsive";

interface DashboardTodoItemProps {
  todo: Todo;
  onToggled?: (id: string, completed: boolean) => void;
}

const PRIORITY_COLORS: Record<Priority, string> = {
  [Priority.HIGH]: "#ef4444",
  [Priority.MEDIUM]: "#f97316",
  [Priority.LOW]: "#eab308",
  [Priority.NONE]: "#71717a",
};

const PRIORITY_LABELS: Record<Priority, string> = {
  [Priority.HIGH]: "High",
  [Priority.MEDIUM]: "Medium",
  [Priority.LOW]: "Low",
  [Priority.NONE]: "None",
};

export function DashboardTodoItem({ todo, onToggled }: DashboardTodoItemProps) {
  const { spacing, fontSize } = useResponsive();
  const [completed, setCompleted] = useState(todo.completed);
  const [isUpdating, setIsUpdating] = useState(false);

  const handleToggle = useCallback(async () => {
    if (isUpdating) return;
    const next = !completed;
    setCompleted(next);
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setIsUpdating(true);
    try {
      await todoApi.updateTodo(todo.id, { completed: next });
      onToggled?.(todo.id, next);
    } catch {
      setCompleted(!next);
    } finally {
      setIsUpdating(false);
    }
  }, [completed, isUpdating, todo.id, onToggled]);

  const hasPriority =
    todo.priority !== undefined && todo.priority !== Priority.NONE;

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm + 2,
        borderBottomWidth: 1,
        borderBottomColor: "rgba(255,255,255,0.04)",
        gap: spacing.sm,
        opacity: completed ? 0.45 : 1,
      }}
    >
      <Checkbox
        isSelected={completed}
        onSelectedChange={() => {
          void handleToggle();
        }}
        isDisabled={isUpdating}
      />

      <Text
        numberOfLines={1}
        style={{
          flex: 1,
          fontSize: fontSize.sm,
          fontWeight: "500",
          color: completed ? "#52525b" : "#e4e4e7",
          textDecorationLine: completed ? "line-through" : "none",
        }}
      >
        {todo.title}
      </Text>

      {hasPriority && todo.priority !== undefined && (
        <Chip
          variant="soft"
          size="sm"
          animation="disable-all"
          style={{
            backgroundColor: `${PRIORITY_COLORS[todo.priority]}1a`,
          }}
        >
          <Chip.Label
            style={{
              fontSize: fontSize.xs,
              color: PRIORITY_COLORS[todo.priority],
              fontWeight: "500",
            }}
          >
            {PRIORITY_LABELS[todo.priority]}
          </Chip.Label>
        </Chip>
      )}
    </View>
  );
}
