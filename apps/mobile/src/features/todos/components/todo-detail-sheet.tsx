import {
  BottomSheetScrollView,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import DateTimePicker from "@react-native-community/datetimepicker";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { Platform, Pressable, View } from "react-native";
import {
  Add01Icon,
  AppIcon,
  Calendar03Icon,
  Cancel01Icon,
  Flag02Icon,
  Folder02Icon,
  Tag01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import type { Project, SubTask, Todo, TodoUpdate } from "../types/todo-types";
import { Priority } from "../types/todo-types";
import { LabelChip } from "./label-chip";
import {
  LabelPickerSheet,
  type LabelPickerSheetRef,
} from "./label-picker-sheet";

export interface TodoDetailSheetRef {
  open: (todo: Todo) => void;
  close: () => void;
}

interface Props {
  projects: Project[];
  onUpdate: (todoId: string, updates: TodoUpdate) => Promise<void>;
  onAddSubtask: (todoId: string, title: string) => Promise<void>;
  onToggleSubtask: (
    todoId: string,
    subtaskId: string,
    completed: boolean,
  ) => Promise<void>;
  onDeleteSubtask: (todoId: string, subtaskId: string) => Promise<void>;
}

const PRIORITY_OPTIONS: { value: Priority; label: string; color: string }[] = [
  { value: Priority.NONE, label: "None", color: "#71717a" },
  { value: Priority.LOW, label: "Low", color: "#eab308" },
  { value: Priority.MEDIUM, label: "Medium", color: "#f97316" },
  { value: Priority.HIGH, label: "High", color: "#ef4444" },
];

function priorityColor(p: Priority): string {
  return PRIORITY_OPTIONS.find((o) => o.value === p)?.color ?? "#71717a";
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export const TodoDetailSheet = forwardRef<TodoDetailSheetRef, Props>(
  (
    { projects, onUpdate, onAddSubtask, onToggleSubtask, onDeleteSubtask },
    ref,
  ) => {
    const [isOpen, setIsOpen] = useState(false);
    const labelPickerRef = useRef<LabelPickerSheetRef>(null);
    const [todo, setTodo] = useState<Todo | null>(null);
    const [title, setTitle] = useState("");
    const [description, setDescription] = useState("");
    const [priority, setPriority] = useState<Priority>(Priority.NONE);
    const [dueDate, setDueDate] = useState<Date | null>(null);
    const [projectId, setProjectId] = useState<string | null>(null);
    const [labels, setLabels] = useState<string[]>([]);
    const [allLabels, setAllLabels] = useState<string[]>([]);
    const [newSubtaskText, setNewSubtaskText] = useState("");
    const [showPriorityPicker, setShowPriorityPicker] = useState(false);
    const [showProjectPicker, setShowProjectPicker] = useState(false);
    const [showDatePicker, setShowDatePicker] = useState(false);

    const { spacing, fontSize } = useResponsive();

    const saveTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
    const scheduleSave = useCallback(
      (field: Partial<TodoUpdate>) => {
        if (!todo) return;
        if (saveTimeout.current) clearTimeout(saveTimeout.current);
        saveTimeout.current = setTimeout(() => onUpdate(todo.id, field), 800);
      },
      [todo, onUpdate],
    );

    useImperativeHandle(ref, () => ({
      open: (t: Todo) => {
        setTodo(t);
        setTitle(t.title);
        setDescription(t.description ?? "");
        setPriority(t.priority);
        setDueDate(t.due_date ? new Date(t.due_date) : null);
        setProjectId(t.project_id ?? null);
        setLabels(t.labels ?? []);
        setAllLabels(t.labels ?? []);
        setNewSubtaskText("");
        setShowPriorityPicker(false);
        setShowProjectPicker(false);
        setShowDatePicker(false);
        setIsOpen(true);
      },
      close: () => setIsOpen(false),
    }));

    const handleAddSubtask = useCallback(async () => {
      if (!todo || !newSubtaskText.trim()) return;
      await onAddSubtask(todo.id, newSubtaskText.trim());
      setNewSubtaskText("");
    }, [todo, newSubtaskText, onAddSubtask]);

    const handleLabelsChange = useCallback(
      (newLabels: string[]) => {
        setLabels(newLabels);
        setAllLabels((prev) => {
          const merged = new Set([...prev, ...newLabels]);
          return Array.from(merged);
        });
        if (!todo) return;
        void onUpdate(todo.id, { labels: newLabels });
      },
      [todo, onUpdate],
    );

    const handleOpenLabelPicker = useCallback(() => {
      setShowPriorityPicker(false);
      setShowProjectPicker(false);
      setShowDatePicker(false);
      labelPickerRef.current?.open(labels, allLabels);
    }, [labels, allLabels]);

    if (!todo) {
      return (
        <>
          <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
            <BottomSheet.Portal>
              <BottomSheet.Overlay />
              <BottomSheet.Content
                snapPoints={["70%", "95%"]}
                enableDynamicSizing={false}
                enablePanDownToClose
                backgroundStyle={{ backgroundColor: "#1c1c1e" }}
                handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
              >
                <View />
              </BottomSheet.Content>
            </BottomSheet.Portal>
          </BottomSheet>
          <LabelPickerSheet ref={labelPickerRef} onDone={handleLabelsChange} />
        </>
      );
    }

    const subtasks: SubTask[] = todo.subtasks ?? [];
    const activeProject = projects.find((p) => p.id === projectId) ?? null;

    const chipStyle = {
      paddingHorizontal: 10,
      paddingVertical: 6,
      borderRadius: 8,
      backgroundColor: "#27272a",
      borderWidth: 1,
      borderColor: "#3f3f46",
      flexDirection: "row" as const,
      alignItems: "center" as const,
      gap: 6,
    };

    return (
      <>
        <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
          <BottomSheet.Portal>
            <BottomSheet.Overlay />
            <BottomSheet.Content
              snapPoints={["70%", "95%"]}
              enableDynamicSizing={false}
              enablePanDownToClose
              backgroundStyle={{ backgroundColor: "#1c1c1e" }}
              handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
            >
              <BottomSheetScrollView
                contentContainerStyle={{
                  padding: 20,
                  gap: 16,
                  paddingBottom: 40,
                }}
                keyboardShouldPersistTaps="handled"
              >
                {/* Title */}
                <BottomSheetTextInput
                  value={title}
                  onChangeText={(text) => {
                    setTitle(text);
                    scheduleSave({ title: text });
                  }}
                  placeholder="Task title"
                  placeholderTextColor="#52525b"
                  style={{
                    fontSize: 20,
                    fontWeight: "600",
                    color: "#f4f4f5",
                    borderBottomWidth: 1,
                    borderBottomColor: "#3f3f46",
                    paddingVertical: 6,
                  }}
                />

                {/* Description */}
                <BottomSheetTextInput
                  value={description}
                  onChangeText={(text) => {
                    setDescription(text);
                    scheduleSave({ description: text });
                  }}
                  placeholder="Add description..."
                  placeholderTextColor="#52525b"
                  multiline
                  style={{
                    fontSize: fontSize.sm,
                    color: "#e4e4e7",
                    minHeight: 48,
                    textAlignVertical: "top",
                  }}
                />

                {/* Chips row */}
                <View
                  style={{
                    flexDirection: "row",
                    flexWrap: "wrap",
                    gap: 8,
                  }}
                >
                  {/* Priority chip */}
                  <Pressable
                    style={chipStyle}
                    onPress={() => {
                      setShowPriorityPicker((v) => !v);
                      setShowProjectPicker(false);
                      setShowDatePicker(false);
                    }}
                  >
                    <AppIcon
                      icon={Flag02Icon}
                      size={14}
                      color={priorityColor(priority)}
                    />
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: priorityColor(priority),
                        fontWeight: "500",
                      }}
                    >
                      {PRIORITY_OPTIONS.find((o) => o.value === priority)
                        ?.label ?? "None"}
                    </Text>
                  </Pressable>

                  {/* Due date chip */}
                  <Pressable
                    style={chipStyle}
                    onPress={() => {
                      setShowDatePicker((v) => !v);
                      setShowPriorityPicker(false);
                      setShowProjectPicker(false);
                    }}
                  >
                    <AppIcon
                      icon={Calendar03Icon}
                      size={14}
                      color={dueDate ? "#16c1ff" : "#71717a"}
                    />
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: dueDate ? "#16c1ff" : "#71717a",
                        fontWeight: "500",
                      }}
                    >
                      {dueDate ? formatDate(dueDate.toISOString()) : "Due date"}
                    </Text>
                  </Pressable>

                  {/* Project chip */}
                  <Pressable
                    style={chipStyle}
                    onPress={() => {
                      setShowProjectPicker((v) => !v);
                      setShowPriorityPicker(false);
                      setShowDatePicker(false);
                    }}
                  >
                    <AppIcon
                      icon={Folder02Icon}
                      size={14}
                      color={activeProject?.color ?? "#71717a"}
                    />
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: activeProject
                          ? (activeProject.color ?? "#a1a1aa")
                          : "#71717a",
                        fontWeight: "500",
                      }}
                    >
                      {activeProject ? activeProject.name : "Project"}
                    </Text>
                  </Pressable>

                  {/* Labels chip */}
                  <Pressable style={chipStyle} onPress={handleOpenLabelPicker}>
                    <AppIcon
                      icon={Tag01Icon}
                      size={14}
                      color={labels.length > 0 ? "#a78bfa" : "#71717a"}
                    />
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: labels.length > 0 ? "#a78bfa" : "#71717a",
                        fontWeight: "500",
                      }}
                    >
                      {labels.length > 0
                        ? `${labels.length} label${labels.length === 1 ? "" : "s"}`
                        : "Labels"}
                    </Text>
                  </Pressable>
                </View>

                {/* Inline priority picker */}
                {showPriorityPicker && (
                  <View
                    style={{
                      backgroundColor: "#27272a",
                      borderRadius: 12,
                      borderWidth: 1,
                      borderColor: "#3f3f46",
                      overflow: "hidden",
                    }}
                  >
                    {PRIORITY_OPTIONS.map((opt, idx) => {
                      const isActive = priority === opt.value;
                      return (
                        <Pressable
                          key={opt.value}
                          onPress={() => {
                            setPriority(opt.value);
                            void onUpdate(todo.id, { priority: opt.value });
                            setShowPriorityPicker(false);
                          }}
                          style={{
                            flexDirection: "row",
                            alignItems: "center",
                            paddingHorizontal: 14,
                            paddingVertical: 11,
                            gap: 10,
                            borderTopWidth: idx > 0 ? 1 : 0,
                            borderTopColor: "#3f3f46",
                          }}
                        >
                          <View
                            style={{
                              width: 10,
                              height: 10,
                              borderRadius: 5,
                              backgroundColor: opt.color,
                            }}
                          />
                          <Text
                            style={{
                              flex: 1,
                              fontSize: fontSize.sm,
                              color: isActive ? opt.color : "#e4e4e7",
                              fontWeight: isActive ? "600" : "400",
                            }}
                          >
                            {opt.label}
                          </Text>
                          {isActive && (
                            <AppIcon
                              icon={Tick02Icon}
                              size={14}
                              color={opt.color}
                            />
                          )}
                        </Pressable>
                      );
                    })}
                  </View>
                )}

                {/* Inline project picker */}
                {showProjectPicker && (
                  <View
                    style={{
                      backgroundColor: "#27272a",
                      borderRadius: 12,
                      borderWidth: 1,
                      borderColor: "#3f3f46",
                      overflow: "hidden",
                    }}
                  >
                    {/* No project option */}
                    <Pressable
                      onPress={() => {
                        setProjectId(null);
                        void onUpdate(todo.id, { project_id: undefined });
                        setShowProjectPicker(false);
                      }}
                      style={{
                        flexDirection: "row",
                        alignItems: "center",
                        paddingHorizontal: 14,
                        paddingVertical: 11,
                        gap: 10,
                      }}
                    >
                      <AppIcon icon={Folder02Icon} size={14} color="#52525b" />
                      <Text
                        style={{
                          flex: 1,
                          fontSize: fontSize.sm,
                          color: projectId === null ? "#16c1ff" : "#e4e4e7",
                          fontWeight: projectId === null ? "600" : "400",
                        }}
                      >
                        No project
                      </Text>
                      {projectId === null && (
                        <AppIcon icon={Tick02Icon} size={14} color="#16c1ff" />
                      )}
                    </Pressable>

                    {projects.map((proj, _idx) => {
                      const isActive = projectId === proj.id;
                      const color = proj.color ?? "#71717a";
                      return (
                        <Pressable
                          key={proj.id}
                          onPress={() => {
                            setProjectId(proj.id);
                            void onUpdate(todo.id, { project_id: proj.id });
                            setShowProjectPicker(false);
                          }}
                          style={{
                            flexDirection: "row",
                            alignItems: "center",
                            paddingHorizontal: 14,
                            paddingVertical: 11,
                            gap: 10,
                            borderTopWidth: 1,
                            borderTopColor: "#3f3f46",
                          }}
                        >
                          <AppIcon
                            icon={Folder02Icon}
                            size={14}
                            color={isActive ? color : "#52525b"}
                          />
                          <Text
                            style={{
                              flex: 1,
                              fontSize: fontSize.sm,
                              color: isActive ? color : "#e4e4e7",
                              fontWeight: isActive ? "600" : "400",
                            }}
                          >
                            {proj.name}
                          </Text>
                          {isActive && (
                            <AppIcon
                              icon={Tick02Icon}
                              size={14}
                              color={color}
                            />
                          )}
                        </Pressable>
                      );
                    })}
                  </View>
                )}

                {/* DateTimePicker */}
                {showDatePicker && (
                  <DateTimePicker
                    value={dueDate ?? new Date()}
                    mode="date"
                    display={Platform.OS === "ios" ? "spinner" : "default"}
                    onChange={(_, date) => {
                      setShowDatePicker(false);
                      if (date) {
                        setDueDate(date);
                        void onUpdate(todo.id, {
                          due_date: date.toISOString(),
                        });
                      }
                    }}
                    minimumDate={new Date()}
                    themeVariant="dark"
                  />
                )}

                {/* Labels */}
                {labels.length > 0 && (
                  <Pressable
                    onPress={handleOpenLabelPicker}
                    style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}
                  >
                    {labels.map((lbl) => (
                      <LabelChip key={lbl} label={lbl} size="sm" />
                    ))}
                  </Pressable>
                )}

                {/* Subtasks header */}
                <View
                  style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      fontWeight: "600",
                      color: "#a1a1aa",
                      textTransform: "uppercase",
                      letterSpacing: 0.8,
                      flex: 1,
                    }}
                  >
                    Subtasks
                  </Text>
                  <Text style={{ fontSize: fontSize.xs, color: "#52525b" }}>
                    {subtasks.filter((s) => s.completed).length}/
                    {subtasks.length}
                  </Text>
                </View>

                {/* Subtask list */}
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
                        void onToggleSubtask(
                          todo.id,
                          subtask.id,
                          !subtask.completed,
                        )
                      }
                    >
                      <View
                        style={{
                          width: 20,
                          height: 20,
                          borderRadius: 10,
                          borderWidth: 2,
                          borderStyle: subtask.completed ? "solid" : "dashed",
                          borderColor: subtask.completed
                            ? "#00bbff"
                            : "#52525b",
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
                        textDecorationLine: subtask.completed
                          ? "line-through"
                          : "none",
                      }}
                    >
                      {subtask.title}
                    </Text>
                    <Pressable
                      onPress={() => void onDeleteSubtask(todo.id, subtask.id)}
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
                  }}
                >
                  {/* Dashed circle placeholder */}
                  <View
                    style={{
                      width: 20,
                      height: 20,
                      borderRadius: 10,
                      borderWidth: 2,
                      borderStyle: "dashed",
                      borderColor: "#3f3f46",
                      flexShrink: 0,
                    }}
                  />
                  <BottomSheetTextInput
                    value={newSubtaskText}
                    onChangeText={setNewSubtaskText}
                    placeholder="Add subtask..."
                    placeholderTextColor="#52525b"
                    style={{
                      flex: 1,
                      color: "#f4f4f5",
                      fontSize: fontSize.sm,
                      borderBottomWidth: 1,
                      borderBottomColor: "#3f3f46",
                      paddingVertical: 6,
                    }}
                    onSubmitEditing={() => void handleAddSubtask()}
                    returnKeyType="done"
                  />
                  <Pressable
                    onPress={() => void handleAddSubtask()}
                    hitSlop={8}
                  >
                    <AppIcon icon={Add01Icon} size={18} color="#00bbff" />
                  </Pressable>
                </View>
              </BottomSheetScrollView>
            </BottomSheet.Content>
          </BottomSheet.Portal>
        </BottomSheet>

        <LabelPickerSheet ref={labelPickerRef} onDone={handleLabelsChange} />
      </>
    );
  },
);
