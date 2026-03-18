import { useRouter } from "expo-router";
import { useCallback } from "react";
import { Alert, Pressable, View } from "react-native";
import {
  AppIcon,
  ArrowRight01Icon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Delete02Icon,
  Flag02Icon,
  Folder02Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  impactHaptic,
  longPressHaptic,
  notificationHaptic,
} from "@/lib/haptics";
import { useResponsive } from "@/lib/responsive";
import { Priority, type Project, type Todo } from "../types/todo-types";
import { LabelChip } from "./label-chip";

interface TodoItemProps {
  todo: Todo;
  projects: Project[];
  onToggleComplete: (todo: Todo) => void;
  onPress?: (todo: Todo) => void;
  onDelete?: (todoId: string) => void;
  selectionMode?: boolean;
  isSelected?: boolean;
  onSelect?: (id: string) => void;
  onLongPress?: (todo: Todo) => void;
}

const PRIORITY_COLORS: Record<Priority, string> = {
  [Priority.HIGH]: "#ef4444",
  [Priority.MEDIUM]: "#f97316",
  [Priority.LOW]: "#eab308",
  [Priority.NONE]: "#71717a",
};

const PRIORITY_BG: Record<Priority, string> = {
  [Priority.HIGH]: "rgba(239,68,68,0.12)",
  [Priority.MEDIUM]: "rgba(249,115,22,0.12)",
  [Priority.LOW]: "rgba(234,179,8,0.12)",
  [Priority.NONE]: "rgba(113,113,122,0.12)",
};

const PRIORITY_LABELS: Record<Priority, string> = {
  [Priority.HIGH]: "High",
  [Priority.MEDIUM]: "Medium",
  [Priority.LOW]: "Low",
  [Priority.NONE]: "None",
};

function formatDueDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());

  if (target.getTime() === today.getTime()) return "Today";
  if (target.getTime() === tomorrow.getTime()) return "Tomorrow";

  const diffDays = Math.round(
    (target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24),
  );
  if (diffDays < 0) return `${Math.abs(diffDays)}d overdue`;
  if (diffDays <= 7) return `In ${diffDays}d`;

  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function TodoItem({
  todo,
  projects,
  onToggleComplete,
  onPress,
  onDelete,
  selectionMode = false,
  isSelected = false,
  onSelect,
  onLongPress,
}: TodoItemProps) {
  const { spacing, fontSize } = useResponsive();
  const router = useRouter();

  const isOverdue =
    !!todo.due_date && new Date(todo.due_date) < new Date() && !todo.completed;

  const isToday =
    !!todo.due_date &&
    !todo.completed &&
    (() => {
      const d = new Date(todo.due_date!);
      const now = new Date();
      return (
        d.getFullYear() === now.getFullYear() &&
        d.getMonth() === now.getMonth() &&
        d.getDate() === now.getDate()
      );
    })();

  const project = projects.find((p) => p.id === todo.project_id);
  const priorityColor = PRIORITY_COLORS[todo.priority];

  const completedSubtasks =
    todo.subtasks?.filter((s) => s.completed).length ?? 0;
  const totalSubtasks = todo.subtasks?.length ?? 0;

  const handleToggle = useCallback(() => {
    if (todo.completed) {
      impactHaptic("medium");
    } else {
      notificationHaptic("success");
    }
    onToggleComplete(todo);
  }, [onToggleComplete, todo]);

  const handlePress = useCallback(() => {
    if (selectionMode) {
      onSelect?.(todo.id);
    } else {
      onPress?.(todo);
    }
  }, [selectionMode, onSelect, onPress, todo]);

  const handleLongPress = useCallback(() => {
    longPressHaptic();
    onLongPress?.(todo);
  }, [onLongPress, todo]);

  const handleDeletePress = useCallback(() => {
    notificationHaptic("warning");
    Alert.alert(
      "Delete Task",
      `Are you sure you want to delete "${todo.title}"?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => onDelete?.(todo.id),
        },
      ],
    );
  }, [todo.id, todo.title, onDelete]);

  const hasChips =
    todo.priority !== Priority.NONE ||
    !!todo.due_date ||
    todo.labels.length > 0 ||
    !!project ||
    totalSubtasks > 0;

  return (
    <Pressable
      onPress={handlePress}
      onLongPress={
        selectionMode
          ? undefined
          : onLongPress
            ? handleLongPress
            : onDelete
              ? handleDeletePress
              : undefined
      }
      accessible={true}
      accessibilityRole="button"
      accessibilityLabel={todo.title}
      accessibilityHint={
        selectionMode
          ? isSelected
            ? "Double tap to deselect"
            : "Double tap to select"
          : "Double tap to open task details"
      }
      accessibilityState={{ selected: isSelected }}
      style={{
        flexDirection: "row",
        alignItems: "flex-start",
        paddingVertical: spacing.md,
        paddingHorizontal: spacing.md,
        borderBottomWidth: 1,
        borderBottomColor: "rgba(255,255,255,0.04)",
        opacity: todo.completed ? 0.4 : 1,
        backgroundColor: isSelected ? "rgba(22,193,255,0.08)" : "transparent",
      }}
    >
      {/* Selection checkbox (shown in selection mode) */}
      {selectionMode && (
        <Pressable
          onPress={() => onSelect?.(todo.id)}
          hitSlop={12}
          accessibilityRole="checkbox"
          accessibilityLabel={`Select ${todo.title}`}
          accessibilityState={{ checked: isSelected }}
          style={{
            width: 22,
            height: 22,
            borderRadius: 11,
            borderWidth: 2,
            borderColor: isSelected ? "#16c1ff" : "#52525b",
            backgroundColor: isSelected ? "#16c1ff" : "transparent",
            alignItems: "center",
            justifyContent: "center",
            marginTop: 2,
            marginRight: spacing.sm + 4,
            flexShrink: 0,
          }}
        >
          {isSelected && <AppIcon icon={Tick02Icon} size={13} color="#000" />}
        </Pressable>
      )}

      {/* Completion checkbox (hidden in selection mode) */}
      {!selectionMode && (
        <Pressable
          onPress={handleToggle}
          hitSlop={12}
          accessibilityRole="checkbox"
          accessibilityLabel={
            todo.completed
              ? `Mark ${todo.title} as incomplete`
              : `Mark ${todo.title} as complete`
          }
          accessibilityState={{ checked: todo.completed }}
          style={{
            width: 22,
            height: 22,
            borderRadius: 11,
            borderWidth: todo.completed ? 0 : 1.5,
            borderColor: priorityColor,
            borderStyle: todo.completed ? "solid" : "dashed",
            backgroundColor: todo.completed
              ? "rgba(63,63,70,0.8)"
              : "transparent",
            alignItems: "center",
            justifyContent: "center",
            marginTop: 2,
            marginRight: spacing.sm + 4,
            flexShrink: 0,
          }}
        >
          {todo.completed && (
            <AppIcon icon={Tick02Icon} size={13} color="#71717a" />
          )}
        </Pressable>
      )}

      {/* Content */}
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text
          numberOfLines={2}
          style={{
            fontSize: fontSize.base,
            fontWeight: "500",
            color: todo.completed ? "#52525b" : "#f4f4f5",
            textDecorationLine: todo.completed ? "line-through" : "none",
            lineHeight: fontSize.base * 1.4,
          }}
        >
          {todo.title}
        </Text>

        {!!todo.description && (
          <Text
            numberOfLines={1}
            style={{
              fontSize: fontSize.xs,
              color: "#71717a",
              marginTop: 3,
            }}
          >
            {todo.description}
          </Text>
        )}

        {hasChips && (
          <View
            style={{
              flexDirection: "row",
              flexWrap: "wrap",
              alignItems: "center",
              gap: 5,
              marginTop: spacing.sm - 2,
            }}
          >
            {/* Due date chip */}
            {!!todo.due_date && (
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  backgroundColor: isOverdue
                    ? "rgba(239,68,68,0.12)"
                    : isToday
                      ? "rgba(34,197,94,0.12)"
                      : "rgba(255,255,255,0.06)",
                  borderRadius: 6,
                  paddingHorizontal: 7,
                  paddingVertical: 3,
                  gap: 4,
                }}
              >
                <AppIcon
                  icon={Calendar03Icon}
                  size={12}
                  color={
                    isOverdue ? "#ef4444" : isToday ? "#22c55e" : "#71717a"
                  }
                />
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: isOverdue
                      ? "#ef4444"
                      : isToday
                        ? "#22c55e"
                        : "#a1a1aa",
                    fontWeight: "500",
                  }}
                >
                  {formatDueDate(todo.due_date)}
                </Text>
              </View>
            )}

            {/* Project chip */}
            {!!project && (
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  backgroundColor: "rgba(255,255,255,0.06)",
                  borderRadius: 6,
                  paddingHorizontal: 7,
                  paddingVertical: 3,
                  gap: 4,
                }}
              >
                <AppIcon
                  icon={Folder02Icon}
                  size={12}
                  color={project.color ?? "#71717a"}
                />
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: project.color ?? "#a1a1aa",
                    fontWeight: "500",
                  }}
                >
                  {project.name}
                </Text>
              </View>
            )}

            {/* Subtasks chip */}
            {totalSubtasks > 0 && (
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  backgroundColor: "rgba(255,255,255,0.06)",
                  borderRadius: 6,
                  paddingHorizontal: 7,
                  paddingVertical: 3,
                  gap: 4,
                }}
              >
                <AppIcon
                  icon={CheckmarkCircle02Icon}
                  size={12}
                  color="#71717a"
                />
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#a1a1aa",
                    fontWeight: "500",
                  }}
                >
                  {completedSubtasks}/{totalSubtasks}
                </Text>
              </View>
            )}

            {/* Label chips */}
            {todo.labels.map((label) => (
              <LabelChip
                key={label}
                label={label}
                size="sm"
                onPress={
                  selectionMode
                    ? undefined
                    : (lbl) => {
                        router.push(
                          `/(app)/(tabs)/todos/label/${encodeURIComponent(lbl)}`,
                        );
                      }
                }
              />
            ))}

            {/* Priority chip */}
            {!!todo.priority && todo.priority !== Priority.NONE && (
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  backgroundColor: PRIORITY_BG[todo.priority],
                  borderRadius: 6,
                  paddingHorizontal: 7,
                  paddingVertical: 3,
                  gap: 4,
                }}
              >
                <AppIcon icon={Flag02Icon} size={12} color={priorityColor} />
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: priorityColor,
                    fontWeight: "500",
                  }}
                >
                  {PRIORITY_LABELS[todo.priority]}
                </Text>
              </View>
            )}
          </View>
        )}
      </View>

      {/* Trailing area */}
      {!selectionMode && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
            marginLeft: spacing.sm,
            alignSelf: "center",
          }}
        >
          {onDelete && (
            <Pressable
              onPress={handleDeletePress}
              hitSlop={8}
              accessibilityRole="button"
              accessibilityLabel={`Delete ${todo.title}`}
              style={{
                width: 28,
                height: 28,
                borderRadius: 8,
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: "rgba(239,68,68,0.08)",
              }}
            >
              <AppIcon icon={Delete02Icon} size={14} color="#ef4444" />
            </Pressable>
          )}
          <AppIcon
            icon={ArrowRight01Icon}
            size={16}
            color="rgba(255,255,255,0.18)"
          />
        </View>
      )}
    </Pressable>
  );
}
