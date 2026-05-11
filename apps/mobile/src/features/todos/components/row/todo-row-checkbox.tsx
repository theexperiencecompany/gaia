import { Pressable } from "react-native";
import { AppIcon, Tick02Icon } from "@/components/icons";
import { Priority } from "../../types/todo-types";

interface TodoRowCheckboxProps {
  completed: boolean;
  priority: Priority;
  onToggle: () => void;
  accessibilityLabel: string;
}

const PRIORITY_BORDER: Record<Priority, string> = {
  [Priority.HIGH]: "#ef4444",
  [Priority.MEDIUM]: "#eab308",
  [Priority.LOW]: "#3b82f6",
  [Priority.NONE]: "#71717a",
};

/**
 * Web parity (apps/web/src/features/todo/components/TodoItem.tsx): a circular
 * checkbox with a dashed border whose colour is driven by priority. When
 * completed, the circle fills with the brand primary and shows a black tick.
 */
export function TodoRowCheckbox({
  completed,
  priority,
  onToggle,
  accessibilityLabel,
}: TodoRowCheckboxProps) {
  const borderColor = PRIORITY_BORDER[priority];
  return (
    <Pressable
      onPress={onToggle}
      hitSlop={10}
      accessibilityRole="checkbox"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ checked: completed }}
      style={{
        width: 28,
        height: 28,
        borderRadius: 14,
        borderWidth: completed ? 0 : 1.5,
        borderColor,
        borderStyle: completed ? "solid" : "dashed",
        backgroundColor: completed ? "#00bbff" : "transparent",
        alignItems: "center",
        justifyContent: "center",
        marginRight: 12,
        flexShrink: 0,
      }}
    >
      {completed ? (
        <AppIcon icon={Tick02Icon} size={16} color="#0a0a0a" />
      ) : null}
    </Pressable>
  );
}
