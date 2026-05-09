import { BottomSheetTextInput, TouchableOpacity } from "@gorhom/bottom-sheet";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";
import {
  Add01Icon,
  AppIcon,
  Cancel01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { impactHaptic } from "@/lib/haptics";
import type { SubTask } from "../../types/todo-types";

interface TodoDetailSubtasksProps {
  todoId: string;
  subtasks: SubTask[];
  onAdd: (todoId: string, title: string) => Promise<void>;
  onToggle: (
    todoId: string,
    subtaskId: string,
    completed: boolean,
  ) => Promise<void>;
  onDelete: (todoId: string, subtaskId: string) => Promise<void>;
}

/**
 * True nested subtask list. The leading visual cue is a small inset block
 * that mimics a corner-down-right indicator (the icon family doesn't
 * include a CornerDownRight glyph), followed by a 28px circular checkbox,
 * inline title, and an X delete affordance.
 */
export function TodoDetailSubtasks({
  todoId,
  subtasks,
  onAdd,
  onToggle,
  onDelete,
}: TodoDetailSubtasksProps) {
  const [draft, setDraft] = useState("");

  const handleAdd = useCallback(async () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    setDraft("");
    impactHaptic("light");
    try {
      await onAdd(todoId, trimmed);
    } catch {
      // hook surfaces error
    }
  }, [draft, onAdd, todoId]);

  const completed = subtasks.filter((s) => s.completed).length;

  return (
    <View className="gap-2">
      <View className="flex-row items-center justify-between">
        <Text className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Subtasks
        </Text>
        {subtasks.length > 0 ? (
          <Text className="text-[11px] text-zinc-500">
            {completed}/{subtasks.length}
          </Text>
        ) : null}
      </View>

      <View className="rounded-2xl bg-zinc-800/30 p-3 gap-2">
        {subtasks.length === 0 ? (
          <Text className="text-[13px] italic text-zinc-500">
            No subtasks yet
          </Text>
        ) : (
          subtasks.map((subtask) => (
            <View
              key={subtask.id}
              className="flex-row items-center gap-3"
              style={{ paddingLeft: 4 }}
            >
              <View
                style={{
                  width: 12,
                  height: 12,
                  marginRight: 2,
                  borderLeftWidth: 1.5,
                  borderBottomWidth: 1.5,
                  borderColor: "#52525b",
                  borderBottomLeftRadius: 4,
                }}
              />
              <Pressable
                onPress={() => {
                  impactHaptic("light");
                  void onToggle(todoId, subtask.id, !subtask.completed);
                }}
                hitSlop={8}
              >
                <View
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 11,
                    borderWidth: 2,
                    borderColor: subtask.completed ? "#00bbff" : "#52525b",
                    backgroundColor: subtask.completed
                      ? "#00bbff"
                      : "transparent",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {subtask.completed ? (
                    <AppIcon icon={Tick02Icon} size={12} color="#000" />
                  ) : null}
                </View>
              </Pressable>
              <Text
                className="flex-1 text-[14px]"
                style={{
                  color: subtask.completed ? "#71717a" : "#e4e4e7",
                  textDecorationLine: subtask.completed
                    ? "line-through"
                    : "none",
                }}
              >
                {subtask.title}
              </Text>
              <Pressable
                onPress={() => void onDelete(todoId, subtask.id)}
                hitSlop={8}
              >
                <AppIcon icon={Cancel01Icon} size={14} color="#71717a" />
              </Pressable>
            </View>
          ))
        )}

        {/* Add subtask row */}
        <View
          className="flex-row items-center gap-3 mt-1"
          style={{ paddingLeft: 4 }}
        >
          <View
            style={{
              width: 12,
              height: 12,
              marginRight: 2,
              borderLeftWidth: 1.5,
              borderBottomWidth: 1.5,
              borderColor: "#3f3f46",
              borderBottomLeftRadius: 4,
            }}
          />
          <View
            style={{
              width: 22,
              height: 22,
              borderRadius: 11,
              borderWidth: 2,
              borderStyle: "dashed",
              borderColor: "#3f3f46",
            }}
          />
          <BottomSheetTextInput
            value={draft}
            onChangeText={setDraft}
            placeholder="Add subtask…"
            placeholderTextColor="#52525b"
            style={{
              flex: 1,
              color: "#f4f4f5",
              fontSize: 14,
              paddingVertical: 4,
            }}
            onSubmitEditing={() => void handleAdd()}
            returnKeyType="done"
          />
          <TouchableOpacity onPress={() => void handleAdd()} hitSlop={8}>
            <AppIcon icon={Add01Icon} size={18} color="#00bbff" />
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}
