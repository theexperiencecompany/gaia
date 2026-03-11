import * as Haptics from "expo-haptics";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";
import { AppIcon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { todoApi } from "@/features/todos/api/todo-api";
import type { Todo } from "@/features/todos/types/todo-types";

interface DashboardTodoItemProps {
  todo: Todo;
  onToggled?: (id: string, completed: boolean) => void;
}

export function DashboardTodoItem({
  todo,
  onToggled,
}: DashboardTodoItemProps) {
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
      <Pressable
        onPress={() => {
          void handleToggle();
        }}
        hitSlop={10}
        style={{
          width: 20,
          height: 20,
          borderRadius: 10,
          borderWidth: completed ? 0 : 1.5,
          borderColor: "#00bbff",
          borderStyle: completed ? "solid" : "dashed",
          backgroundColor: completed ? "rgba(63,63,70,0.8)" : "transparent",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        {completed && <AppIcon icon={Tick02Icon} size={11} color="#71717a" />}
      </Pressable>

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
    </View>
  );
}
