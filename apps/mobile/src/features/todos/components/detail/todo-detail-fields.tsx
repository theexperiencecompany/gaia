import { BottomSheetTextInput } from "@gorhom/bottom-sheet";
import DateTimePicker from "@react-native-community/datetimepicker";
import { useCallback, useMemo, useRef, useState } from "react";
import { Platform, Pressable, View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  Cancel01Icon,
  Clock04Icon,
  Flag02Icon,
  Folder02Icon,
  RepeatIcon,
  Tag01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { selectionHaptic } from "@/lib/haptics";
import type { Project, Todo, TodoUpdate } from "../../types/todo-types";
import { Priority } from "../../types/todo-types";
import { LabelChip } from "../label-chip";
import {
  LabelPickerSheet,
  type LabelPickerSheetRef,
} from "../label-picker-sheet";
import {
  RecurrencePickerSheet,
  type RecurrencePickerSheetRef,
} from "../sheets/recurrence-picker-sheet";

interface TodoDetailFieldsProps {
  todo: Todo;
  projects: Project[];
  onChange: (update: TodoUpdate) => void;
}

const PRIORITY_OPTIONS: {
  value: Priority;
  label: string;
  color: string;
}[] = [
  { value: Priority.NONE, label: "None", color: "#71717a" },
  { value: Priority.LOW, label: "Low", color: "#60a5fa" },
  { value: Priority.MEDIUM, label: "Medium", color: "#facc15" },
  { value: Priority.HIGH, label: "High", color: "#f87171" },
];

function priorityMeta(p: Priority): { label: string; color: string } {
  return PRIORITY_OPTIONS.find((o) => o.value === p) ?? PRIORITY_OPTIONS[0];
}

function deviceTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
}

function formatDate(d: Date): string {
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatTime(d: Date): string {
  return d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

function summariseRrule(rrule: string): string {
  const map = new Map<string, string>();
  for (const part of rrule.split(";")) {
    const [k, v] = part.split("=");
    if (k && v) map.set(k.toUpperCase(), v);
  }
  const freq = map.get("FREQ");
  const interval = Number.parseInt(map.get("INTERVAL") ?? "1", 10);
  if (!freq) return "Custom";
  const noun =
    freq === "DAILY"
      ? "day"
      : freq === "WEEKLY"
        ? "week"
        : freq === "MONTHLY"
          ? "month"
          : "year";
  if (interval === 1) {
    return `Every ${noun}`;
  }
  return `Every ${interval} ${noun}s`;
}

interface FieldRowProps {
  icon: React.ComponentProps<typeof AppIcon>["icon"];
  label: string;
  value: string;
  iconColor?: string;
  valueColor?: string;
  onPress: () => void;
  trailing?: React.ReactNode;
}

function FieldRow({
  icon,
  label,
  value,
  iconColor,
  valueColor,
  onPress,
  trailing,
}: FieldRowProps) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        paddingHorizontal: 14,
        paddingVertical: 14,
        borderRadius: 16,
        backgroundColor: pressed ? "rgba(63,63,70,0.6)" : "rgba(39,39,42,0.30)",
      })}
    >
      <AppIcon icon={icon} size={16} color={iconColor ?? "#a1a1aa"} />
      <Text
        style={{
          fontSize: 13,
          color: "#a1a1aa",
          fontWeight: "500",
          width: 88,
        }}
      >
        {label}
      </Text>
      <Text
        style={{
          flex: 1,
          fontSize: 14,
          color: valueColor ?? "#f4f4f5",
          fontWeight: "500",
        }}
        numberOfLines={1}
      >
        {value}
      </Text>
      {trailing}
    </Pressable>
  );
}

export function TodoDetailFields({
  todo,
  projects,
  onChange,
}: TodoDetailFieldsProps) {
  const labelPickerRef = useRef<LabelPickerSheetRef>(null);
  const recurrenceSheetRef = useRef<RecurrencePickerSheetRef>(null);

  const [title, setTitle] = useState(todo.title);
  const [description, setDescription] = useState(todo.description ?? "");
  const [showPriorityPicker, setShowPriorityPicker] = useState(false);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [showTimePicker, setShowTimePicker] = useState(false);

  const dueDate = todo.due_date ? new Date(todo.due_date) : null;
  const project = useMemo(
    () => projects.find((p) => p.id === todo.project_id) ?? null,
    [projects, todo.project_id],
  );
  const priorityInfo = priorityMeta(todo.priority);

  const commitTitle = useCallback(() => {
    const trimmed = title.trim();
    if (trimmed && trimmed !== todo.title) {
      onChange({ title: trimmed });
    } else if (!trimmed) {
      setTitle(todo.title);
    }
  }, [title, todo.title, onChange]);

  const commitDescription = useCallback(() => {
    if (description !== (todo.description ?? "")) {
      onChange({ description });
    }
  }, [description, todo.description, onChange]);

  const handleDateChange = useCallback(
    (_: unknown, picked?: Date) => {
      if (Platform.OS !== "ios") setShowDatePicker(false);
      if (!picked) return;
      const next = dueDate ? new Date(dueDate) : new Date();
      next.setFullYear(picked.getFullYear());
      next.setMonth(picked.getMonth());
      next.setDate(picked.getDate());
      onChange({
        due_date: next.toISOString(),
        due_date_timezone: deviceTimezone(),
      });
    },
    [dueDate, onChange],
  );

  const handleTimeChange = useCallback(
    (_: unknown, picked?: Date) => {
      if (Platform.OS !== "ios") setShowTimePicker(false);
      if (!picked || !dueDate) return;
      const next = new Date(dueDate);
      next.setHours(picked.getHours());
      next.setMinutes(picked.getMinutes());
      next.setSeconds(0);
      onChange({
        due_date: next.toISOString(),
        due_date_timezone: deviceTimezone(),
      });
    },
    [dueDate, onChange],
  );

  const clearDueDate = useCallback(() => {
    selectionHaptic();
    onChange({ due_date: undefined });
  }, [onChange]);

  const handleLabelsChange = useCallback(
    (labels: string[]) => {
      onChange({ labels });
    },
    [onChange],
  );

  const handleRecurrenceChange = useCallback(
    (rrule: string | null) => {
      onChange({ recurrence: rrule ?? undefined });
    },
    [onChange],
  );

  const closeAllPickers = () => {
    setShowPriorityPicker(false);
    setShowProjectPicker(false);
    setShowDatePicker(false);
    setShowTimePicker(false);
  };

  return (
    <>
      <View style={{ gap: 12 }}>
        {/* Title */}
        <BottomSheetTextInput
          value={title}
          onChangeText={setTitle}
          onBlur={commitTitle}
          placeholder="Task title"
          placeholderTextColor="#52525b"
          multiline
          style={{
            fontSize: 18,
            fontWeight: "500",
            color: "#f4f4f5",
            paddingVertical: 8,
          }}
        />

        {/* Description */}
        <BottomSheetTextInput
          value={description}
          onChangeText={setDescription}
          onBlur={commitDescription}
          placeholder="Add description…"
          placeholderTextColor="#52525b"
          multiline
          style={{
            fontSize: 14,
            color: "#d4d4d8",
            paddingVertical: 6,
            minHeight: 36,
            textAlignVertical: "top",
          }}
        />

        {/* Field rows */}
        <View style={{ gap: 6 }}>
          <FieldRow
            icon={Calendar03Icon}
            label="Due date"
            value={dueDate ? formatDate(dueDate) : "Not set"}
            iconColor={dueDate ? "#00bbff" : "#71717a"}
            valueColor={dueDate ? "#f4f4f5" : "#71717a"}
            onPress={() => {
              selectionHaptic();
              closeAllPickers();
              setShowDatePicker(true);
            }}
            trailing={
              dueDate ? (
                <Pressable onPress={clearDueDate} hitSlop={8}>
                  <AppIcon icon={Cancel01Icon} size={14} color="#71717a" />
                </Pressable>
              ) : null
            }
          />
          {showDatePicker ? (
            <DateTimePicker
              value={dueDate ?? new Date()}
              mode="date"
              display={Platform.OS === "ios" ? "inline" : "default"}
              themeVariant="dark"
              onChange={handleDateChange}
            />
          ) : null}

          {dueDate ? (
            <>
              <FieldRow
                icon={Clock04Icon}
                label="Time"
                value={formatTime(dueDate)}
                onPress={() => {
                  selectionHaptic();
                  closeAllPickers();
                  setShowTimePicker(true);
                }}
              />
              {showTimePicker ? (
                <DateTimePicker
                  value={dueDate}
                  mode="time"
                  display={Platform.OS === "ios" ? "spinner" : "default"}
                  themeVariant="dark"
                  onChange={handleTimeChange}
                />
              ) : null}
            </>
          ) : null}

          <FieldRow
            icon={Flag02Icon}
            label="Priority"
            value={priorityInfo.label}
            iconColor={priorityInfo.color}
            valueColor={priorityInfo.color}
            onPress={() => {
              selectionHaptic();
              closeAllPickers();
              setShowPriorityPicker((v) => !v);
            }}
          />
          {showPriorityPicker ? (
            <View className="rounded-2xl bg-zinc-800/30 p-1">
              {PRIORITY_OPTIONS.map((opt) => {
                const active = todo.priority === opt.value;
                return (
                  <Pressable
                    key={opt.value}
                    onPress={() => {
                      selectionHaptic();
                      onChange({ priority: opt.value });
                      setShowPriorityPicker(false);
                    }}
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 12,
                      paddingHorizontal: 14,
                      paddingVertical: 11,
                      borderRadius: 12,
                    }}
                  >
                    <AppIcon icon={Flag02Icon} size={14} color={opt.color} />
                    <Text
                      style={{
                        flex: 1,
                        fontSize: 14,
                        color: active ? opt.color : "#e4e4e7",
                        fontWeight: active ? "600" : "400",
                      }}
                    >
                      {opt.label}
                    </Text>
                    {active ? (
                      <AppIcon icon={Tick02Icon} size={14} color={opt.color} />
                    ) : null}
                  </Pressable>
                );
              })}
            </View>
          ) : null}

          <FieldRow
            icon={Folder02Icon}
            label="Project"
            value={project ? project.name : "Inbox"}
            iconColor={project?.color ?? "#71717a"}
            valueColor={project ? "#f4f4f5" : "#71717a"}
            onPress={() => {
              selectionHaptic();
              closeAllPickers();
              setShowProjectPicker((v) => !v);
            }}
          />
          {showProjectPicker ? (
            <View className="rounded-2xl bg-zinc-800/30 p-1">
              <Pressable
                onPress={() => {
                  selectionHaptic();
                  onChange({ project_id: undefined });
                  setShowProjectPicker(false);
                }}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 12,
                  paddingHorizontal: 14,
                  paddingVertical: 11,
                  borderRadius: 12,
                }}
              >
                <AppIcon icon={Folder02Icon} size={14} color="#71717a" />
                <Text
                  style={{
                    flex: 1,
                    fontSize: 14,
                    color: !project ? "#00bbff" : "#e4e4e7",
                    fontWeight: !project ? "600" : "400",
                  }}
                >
                  No project
                </Text>
                {!project ? (
                  <AppIcon icon={Tick02Icon} size={14} color="#00bbff" />
                ) : null}
              </Pressable>
              {projects.map((proj) => {
                const active = todo.project_id === proj.id;
                const color = proj.color ?? "#71717a";
                return (
                  <Pressable
                    key={proj.id}
                    onPress={() => {
                      selectionHaptic();
                      onChange({ project_id: proj.id });
                      setShowProjectPicker(false);
                    }}
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 12,
                      paddingHorizontal: 14,
                      paddingVertical: 11,
                      borderRadius: 12,
                    }}
                  >
                    <AppIcon icon={Folder02Icon} size={14} color={color} />
                    <Text
                      style={{
                        flex: 1,
                        fontSize: 14,
                        color: active ? color : "#e4e4e7",
                        fontWeight: active ? "600" : "400",
                      }}
                    >
                      {proj.name}
                    </Text>
                    {active ? (
                      <AppIcon icon={Tick02Icon} size={14} color={color} />
                    ) : null}
                  </Pressable>
                );
              })}
            </View>
          ) : null}

          <FieldRow
            icon={Tag01Icon}
            label="Labels"
            value={
              todo.labels.length > 0
                ? `${todo.labels.length} label${todo.labels.length === 1 ? "" : "s"}`
                : "Add labels"
            }
            iconColor={todo.labels.length > 0 ? "#a78bfa" : "#71717a"}
            valueColor={todo.labels.length > 0 ? "#f4f4f5" : "#71717a"}
            onPress={() => {
              selectionHaptic();
              closeAllPickers();
              labelPickerRef.current?.open(todo.labels, todo.labels);
            }}
          />
          {todo.labels.length > 0 ? (
            <View
              className="flex-row flex-wrap"
              style={{ gap: 6, paddingHorizontal: 4 }}
            >
              {todo.labels.map((lbl) => (
                <LabelChip key={lbl} label={lbl} size="sm" />
              ))}
            </View>
          ) : null}

          <FieldRow
            icon={RepeatIcon}
            label="Repeat"
            value={todo.recurrence ? summariseRrule(todo.recurrence) : "Never"}
            iconColor={todo.recurrence ? "#00bbff" : "#71717a"}
            valueColor={todo.recurrence ? "#f4f4f5" : "#71717a"}
            onPress={() => {
              selectionHaptic();
              closeAllPickers();
              recurrenceSheetRef.current?.open(todo.recurrence ?? null);
            }}
          />
        </View>
      </View>

      <LabelPickerSheet ref={labelPickerRef} onDone={handleLabelsChange} />
      <RecurrencePickerSheet
        ref={recurrenceSheetRef}
        onDone={handleRecurrenceChange}
      />
    </>
  );
}
