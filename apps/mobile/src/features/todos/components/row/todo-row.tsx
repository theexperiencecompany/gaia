import { useCallback, useRef } from "react";
import {
  ActionSheetIOS,
  Animated,
  Platform,
  Pressable,
  View,
} from "react-native";
import { Swipeable } from "react-native-gesture-handler";
import {
  AppIcon,
  Delete02Icon,
  Tick02Icon,
  Timer02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  impactHaptic,
  notificationHaptic,
  selectionHaptic,
} from "@/lib/haptics";
import { Priority, type Project, type Todo } from "../../types/todo-types";
import { TodoRowCheckbox } from "./todo-row-checkbox";
import { TodoRowMeta } from "./todo-row-meta";
import { TodoRowTrailing } from "./todo-row-trailing";

interface TodoRowProps {
  todo: Todo;
  project: Project | undefined;
  onToggleComplete: (todo: Todo) => void;
  onPress: (todo: Todo) => void;
  onDelete: (todo: Todo) => void;
  onSnooze: (todo: Todo) => void;
  onLongPress: (todo: Todo) => void;
  onOpenMenu: (todo: Todo) => void;
  selectionMode: boolean;
  isSelected: boolean;
  onSelect: (id: string) => void;
}

const PRIORITY_FLAG_COLOR: Record<Priority, string | null> = {
  [Priority.HIGH]: "#f87171",
  [Priority.MEDIUM]: "#facc15",
  [Priority.LOW]: "#60a5fa",
  [Priority.NONE]: null,
};

const SWIPE_COMPLETE_THRESHOLD = 80;
const SWIPE_DELETE_THRESHOLD = 160;

/**
 * Single todo row. Uses `react-native-gesture-handler` Swipeable for
 * swipe-right (complete, threshold 80) and swipe-left (snooze at 80,
 * delete past 160). Tapping the title area opens the detail sheet;
 * tapping the leading checkbox toggles completion.
 *
 * Multi-select mode disables the swipe entirely and converts the
 * trailing slot to a selection circle.
 */
export function TodoRow({
  todo,
  project,
  onToggleComplete,
  onPress,
  onDelete,
  onSnooze,
  onLongPress,
  onOpenMenu,
  selectionMode,
  isSelected,
  onSelect,
}: TodoRowProps) {
  const swipeableRef = useRef<Swipeable>(null);

  const handleToggle = useCallback(() => {
    if (todo.completed) {
      impactHaptic("light");
    } else {
      notificationHaptic("success");
    }
    onToggleComplete(todo);
  }, [onToggleComplete, todo]);

  const handlePress = useCallback(() => {
    if (selectionMode) {
      onSelect(todo.id);
      return;
    }
    onPress(todo);
  }, [selectionMode, onSelect, onPress, todo]);

  const handleLongPress = useCallback(() => {
    if (selectionMode) return;
    impactHaptic("medium");
    onLongPress(todo);
  }, [selectionMode, onLongPress, todo]);

  const handleSelect = useCallback(() => {
    onSelect(todo.id);
  }, [onSelect, todo.id]);

  const handleMenu = useCallback(() => {
    if (Platform.OS === "ios") {
      ActionSheetIOS.showActionSheetWithOptions(
        {
          options: ["Edit", "Snooze", "Delete", "Cancel"],
          destructiveButtonIndex: 2,
          cancelButtonIndex: 3,
        },
        (idx) => {
          if (idx === 0) onPress(todo);
          else if (idx === 1) onSnooze(todo);
          else if (idx === 2) onDelete(todo);
        },
      );
      return;
    }
    onOpenMenu(todo);
  }, [onPress, onSnooze, onDelete, onOpenMenu, todo]);

  const renderLeftActions = useCallback(
    (progress: Animated.AnimatedInterpolation<number>) => {
      const translateX = progress.interpolate({
        inputRange: [0, 1],
        outputRange: [-SWIPE_COMPLETE_THRESHOLD, 0],
      });
      return (
        <Animated.View
          style={{
            transform: [{ translateX }],
            justifyContent: "center",
            alignItems: "flex-end",
            width: SWIPE_COMPLETE_THRESHOLD,
            paddingRight: 6,
          }}
        >
          <View
            style={{
              width: SWIPE_COMPLETE_THRESHOLD - 12,
              height: "100%",
              backgroundColor: "#22c55e",
              borderRadius: 16,
              justifyContent: "center",
              alignItems: "center",
              gap: 4,
            }}
          >
            <AppIcon icon={Tick02Icon} size={18} color="#0a0a0a" />
            <Text style={{ fontSize: 10, color: "#0a0a0a", fontWeight: "600" }}>
              Done
            </Text>
          </View>
        </Animated.View>
      );
    },
    [],
  );

  const renderRightActions = useCallback(
    (progress: Animated.AnimatedInterpolation<number>) => {
      const translateX = progress.interpolate({
        inputRange: [0, 1],
        outputRange: [SWIPE_DELETE_THRESHOLD, 0],
      });
      return (
        <Animated.View
          style={{
            transform: [{ translateX }],
            justifyContent: "center",
            alignItems: "flex-start",
            width: SWIPE_DELETE_THRESHOLD,
            flexDirection: "row",
            gap: 6,
            paddingLeft: 6,
          }}
        >
          <Pressable
            onPress={() => {
              swipeableRef.current?.close();
              onSnooze(todo);
            }}
            style={{
              width: SWIPE_COMPLETE_THRESHOLD - 12,
              height: "100%",
              backgroundColor: "#f59e0b",
              borderRadius: 16,
              justifyContent: "center",
              alignItems: "center",
              gap: 4,
            }}
          >
            <AppIcon icon={Timer02Icon} size={18} color="#0a0a0a" />
            <Text style={{ fontSize: 10, color: "#0a0a0a", fontWeight: "600" }}>
              Snooze
            </Text>
          </Pressable>
          <Pressable
            onPress={() => {
              swipeableRef.current?.close();
              onDelete(todo);
            }}
            style={{
              width: SWIPE_COMPLETE_THRESHOLD - 12,
              height: "100%",
              backgroundColor: "#ef4444",
              borderRadius: 16,
              justifyContent: "center",
              alignItems: "center",
              gap: 4,
            }}
          >
            <AppIcon icon={Delete02Icon} size={18} color="#0a0a0a" />
            <Text style={{ fontSize: 10, color: "#0a0a0a", fontWeight: "600" }}>
              Delete
            </Text>
          </Pressable>
        </Animated.View>
      );
    },
    [onSnooze, onDelete, todo],
  );

  const handleSwipeOpen = useCallback(
    (direction: "left" | "right") => {
      if (direction === "left") {
        swipeableRef.current?.close();
        impactHaptic("medium");
        onToggleComplete(todo);
      } else if (direction === "right") {
        // Right-side actions revealed — user must tap one of the buttons.
        selectionHaptic();
      }
    },
    [onToggleComplete, todo],
  );

  const flagColor = PRIORITY_FLAG_COLOR[todo.priority];
  const titleColor = todo.completed ? "#71717a" : "#f4f4f5";
  const cardBg = isSelected ? "rgba(39,39,42,0.70)" : "rgba(39,39,42,0.30)";

  return (
    <Swipeable
      ref={swipeableRef}
      enabled={!selectionMode}
      friction={2}
      leftThreshold={SWIPE_COMPLETE_THRESHOLD}
      rightThreshold={SWIPE_COMPLETE_THRESHOLD}
      renderLeftActions={renderLeftActions}
      renderRightActions={renderRightActions}
      onSwipeableOpen={handleSwipeOpen}
    >
      <View collapsable={false}>
        <Pressable
          onPress={handlePress}
          onLongPress={selectionMode ? undefined : handleLongPress}
          accessible
          accessibilityRole="button"
          accessibilityLabel={todo.title}
          accessibilityState={{ selected: isSelected }}
          style={{
            flexDirection: "row",
            alignItems: "center",
            backgroundColor: cardBg,
            borderRadius: 16,
            paddingHorizontal: 14,
            paddingVertical: 12,
            marginHorizontal: 16,
            marginVertical: 4,
            opacity: todo.completed ? 0.6 : 1,
            minHeight: 64,
          }}
        >
          <TodoRowCheckbox
            completed={todo.completed}
            priority={todo.priority}
            onToggle={selectionMode ? handleSelect : handleToggle}
            accessibilityLabel={
              todo.completed
                ? `Mark ${todo.title} incomplete`
                : `Mark ${todo.title} complete`
            }
          />

          {flagColor ? (
            <View
              style={{
                width: 4,
                height: 16,
                borderRadius: 2,
                backgroundColor: flagColor,
                marginRight: 8,
              }}
            />
          ) : null}

          <View style={{ flex: 1, minWidth: 0 }}>
            <Text
              numberOfLines={1}
              style={{
                fontSize: 15,
                fontWeight: "500",
                color: titleColor,
                textDecorationLine: todo.completed ? "line-through" : "none",
              }}
            >
              {todo.title}
            </Text>
            <TodoRowMeta todo={todo} project={project} />
          </View>

          <TodoRowTrailing
            selectionMode={selectionMode}
            isSelected={isSelected}
            onSelect={handleSelect}
            onMenu={handleMenu}
          />
        </Pressable>
      </View>
    </Swipeable>
  );
}
