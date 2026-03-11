import BottomSheet, {
  BottomSheetScrollView,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { Pressable, View } from "react-native";
import {
  Add01Icon,
  AppIcon,
  Cancel01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Subtask, Todo } from "../types/todo-types";

export interface TodoDetailSheetRef {
  open: (todo: Todo) => void;
  close: () => void;
}

interface TodoDetailSheetProps {
  onUpdateSubtask: (
    todoId: string,
    subtaskId: string,
    completed: boolean,
  ) => void;
  onAddSubtask: (todoId: string, title: string) => void;
  onDeleteSubtask: (todoId: string, subtaskId: string) => void;
}

export const TodoDetailSheet = forwardRef<
  TodoDetailSheetRef,
  TodoDetailSheetProps
>(({ onUpdateSubtask, onAddSubtask, onDeleteSubtask }, ref) => {
  const bottomSheetRef = useRef<BottomSheet>(null);
  const [todo, setTodo] = useState<Todo | null>(null);
  const [newSubtaskText, setNewSubtaskText] = useState("");
  const { spacing, fontSize } = useResponsive();

  useImperativeHandle(ref, () => ({
    open: (t: Todo) => {
      setTodo(t);
      bottomSheetRef.current?.expand();
    },
    close: () => bottomSheetRef.current?.close(),
  }));

  const handleAddSubtask = () => {
    if (!todo || !newSubtaskText.trim()) return;
    onAddSubtask(todo.id, newSubtaskText.trim());
    setNewSubtaskText("");
  };

  if (!todo) return null;

  const subtasks: Subtask[] = todo.subtasks ?? [];

  return (
    <BottomSheet
      ref={bottomSheetRef}
      index={-1}
      snapPoints={["60%", "90%"]}
      enablePanDownToClose
      backgroundStyle={{ backgroundColor: "#1c1c1e" }}
      handleIndicatorStyle={{ backgroundColor: "#3f3f46" }}
    >
      <BottomSheetScrollView
        contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}
      >
        {/* Title */}
        <Text
          style={{ fontSize: fontSize.lg, fontWeight: "600", color: "#fff" }}
        >
          {todo.title}
        </Text>

        {/* Subtasks section label */}
        <Text
          style={{
            fontSize: fontSize.sm,
            fontWeight: "600",
            color: "#a1a1aa",
            textTransform: "uppercase",
            letterSpacing: 0.8,
          }}
        >
          Subtasks
        </Text>

        {subtasks.map((subtask) => (
          <View
            key={subtask.id}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.sm,
            }}
          >
            <Pressable
              onPress={() =>
                onUpdateSubtask(todo.id, subtask.id, !subtask.completed)
              }
            >
              <View
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: 10,
                  borderWidth: 2,
                  borderColor: subtask.completed ? "#00bbff" : "#52525b",
                  backgroundColor: subtask.completed
                    ? "#00bbff"
                    : "transparent",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {subtask.completed && (
                  <AppIcon icon={Tick02Icon} size={12} color="#000" />
                )}
              </View>
            </Pressable>
            <Text
              style={{
                flex: 1,
                fontSize: fontSize.sm,
                color: subtask.completed ? "#71717a" : "#e4e4e7",
                textDecorationLine: subtask.completed ? "line-through" : "none",
              }}
            >
              {subtask.title}
            </Text>
            <Pressable
              onPress={() => onDeleteSubtask(todo.id, subtask.id)}
              hitSlop={8}
            >
              <AppIcon icon={Cancel01Icon} size={14} color="#71717a" />
            </Pressable>
          </View>
        ))}

        {subtasks.length === 0 && (
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#52525b",
              fontStyle: "italic",
            }}
          >
            No subtasks yet
          </Text>
        )}

        {/* Add subtask input */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
            marginTop: spacing.xs,
          }}
        >
          <BottomSheetTextInput
            value={newSubtaskText}
            onChangeText={setNewSubtaskText}
            placeholder="Add subtask..."
            placeholderTextColor="#52525b"
            style={{
              flex: 1,
              color: "#fff",
              fontSize: fontSize.sm,
              borderBottomWidth: 1,
              borderBottomColor: "#3f3f46",
              paddingVertical: spacing.xs,
            }}
            onSubmitEditing={handleAddSubtask}
            returnKeyType="done"
          />
          <Pressable onPress={handleAddSubtask} hitSlop={8}>
            <AppIcon icon={Add01Icon} size={18} color="#00bbff" />
          </Pressable>
        </View>
      </BottomSheetScrollView>
    </BottomSheet>
  );
});
