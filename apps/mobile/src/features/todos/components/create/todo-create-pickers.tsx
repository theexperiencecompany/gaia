import DateTimePicker from "@react-native-community/datetimepicker";
import { useCallback, useRef, useState } from "react";
import { Platform, Pressable, View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  Flag02Icon,
  Folder02Icon,
  Tag01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { selectionHaptic } from "@/lib/haptics";
import { Priority, type Project } from "../../types/todo-types";
import {
  LabelPickerSheet,
  type LabelPickerSheetRef,
} from "../label-picker-sheet";

interface TodoCreatePickersProps {
  dueDate: Date | null;
  priority: Priority;
  projectId: string | undefined;
  labels: string[];
  projects: Project[];
  onChangeDueDate: (date: Date | null) => void;
  onChangePriority: (priority: Priority) => void;
  onChangeProjectId: (id: string | undefined) => void;
  onChangeLabels: (labels: string[]) => void;
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

function PickerButton({
  icon,
  active,
  activeColor,
  caption,
  onPress,
}: {
  icon: React.ComponentProps<typeof AppIcon>["icon"];
  active: boolean;
  activeColor?: string;
  caption?: string;
  onPress: () => void;
}) {
  const tint = active ? (activeColor ?? "#00bbff") : "#a1a1aa";
  return (
    <Pressable
      onPress={onPress}
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        paddingHorizontal: 10,
        paddingVertical: 8,
        borderRadius: 12,
        backgroundColor: active ? "rgba(0,187,255,0.08)" : "rgba(63,63,70,0.4)",
      }}
    >
      <AppIcon icon={icon} size={16} color={tint} />
      {caption ? (
        <Text
          style={{
            fontSize: 12,
            color: tint,
            fontWeight: "500",
            maxWidth: 96,
          }}
          numberOfLines={1}
        >
          {caption}
        </Text>
      ) : null}
    </Pressable>
  );
}

export function TodoCreatePickers({
  dueDate,
  priority,
  projectId,
  labels,
  projects,
  onChangeDueDate,
  onChangePriority,
  onChangeProjectId,
  onChangeLabels,
}: TodoCreatePickersProps) {
  const labelPickerRef = useRef<LabelPickerSheetRef>(null);
  const [showDate, setShowDate] = useState(false);
  const [showPriority, setShowPriority] = useState(false);
  const [showProject, setShowProject] = useState(false);

  const closeOthers = (keep: "date" | "priority" | "project" | null) => {
    if (keep !== "date") setShowDate(false);
    if (keep !== "priority") setShowPriority(false);
    if (keep !== "project") setShowProject(false);
  };

  const handleDateChange = useCallback(
    (_: unknown, picked?: Date) => {
      if (Platform.OS !== "ios") setShowDate(false);
      if (!picked) return;
      onChangeDueDate(picked);
    },
    [onChangeDueDate],
  );

  const project = projects.find((p) => p.id === projectId) ?? null;
  const priorityInfo =
    PRIORITY_OPTIONS.find((o) => o.value === priority) ?? PRIORITY_OPTIONS[0];

  const dateCaption = dueDate
    ? dueDate.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      })
    : undefined;

  return (
    <View>
      <View
        className="flex-row"
        style={{
          gap: 8,
          paddingHorizontal: 12,
          paddingVertical: 8,
          flexWrap: "wrap",
        }}
      >
        <PickerButton
          icon={Calendar03Icon}
          active={!!dueDate}
          caption={dateCaption}
          onPress={() => {
            selectionHaptic();
            closeOthers("date");
            setShowDate((v) => !v);
          }}
        />
        <PickerButton
          icon={Flag02Icon}
          active={priority !== Priority.NONE}
          activeColor={priorityInfo.color}
          caption={priority !== Priority.NONE ? priorityInfo.label : undefined}
          onPress={() => {
            selectionHaptic();
            closeOthers("priority");
            setShowPriority((v) => !v);
          }}
        />
        <PickerButton
          icon={Folder02Icon}
          active={!!project}
          activeColor={project?.color ?? "#00bbff"}
          caption={project?.name}
          onPress={() => {
            selectionHaptic();
            closeOthers("project");
            setShowProject((v) => !v);
          }}
        />
        <PickerButton
          icon={Tag01Icon}
          active={labels.length > 0}
          activeColor="#a78bfa"
          caption={labels.length > 0 ? `${labels.length}` : undefined}
          onPress={() => {
            selectionHaptic();
            closeOthers(null);
            labelPickerRef.current?.open(labels, labels);
          }}
        />
      </View>

      {showDate ? (
        <View style={{ paddingHorizontal: 12, paddingBottom: 8 }}>
          <DateTimePicker
            value={dueDate ?? new Date()}
            mode="date"
            display={Platform.OS === "ios" ? "compact" : "default"}
            themeVariant="dark"
            onChange={handleDateChange}
          />
          {dueDate ? (
            <Pressable
              onPress={() => onChangeDueDate(null)}
              style={{ alignSelf: "flex-start", paddingVertical: 6 }}
            >
              <Text style={{ fontSize: 12, color: "#71717a" }}>Clear date</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      {showPriority ? (
        <View
          className="rounded-2xl bg-zinc-800/30"
          style={{ marginHorizontal: 12, marginBottom: 8, padding: 4 }}
        >
          {PRIORITY_OPTIONS.map((opt) => {
            const active = priority === opt.value;
            return (
              <Pressable
                key={opt.value}
                onPress={() => {
                  selectionHaptic();
                  onChangePriority(opt.value);
                  setShowPriority(false);
                }}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 12,
                  paddingHorizontal: 12,
                  paddingVertical: 10,
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

      {showProject ? (
        <View
          className="rounded-2xl bg-zinc-800/30"
          style={{ marginHorizontal: 12, marginBottom: 8, padding: 4 }}
        >
          <Pressable
            onPress={() => {
              selectionHaptic();
              onChangeProjectId(undefined);
              setShowProject(false);
            }}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 12,
              paddingHorizontal: 12,
              paddingVertical: 10,
              borderRadius: 12,
            }}
          >
            <AppIcon icon={Folder02Icon} size={14} color="#71717a" />
            <Text
              style={{
                flex: 1,
                fontSize: 14,
                color: !projectId ? "#00bbff" : "#e4e4e7",
                fontWeight: !projectId ? "600" : "400",
              }}
            >
              No project
            </Text>
            {!projectId ? (
              <AppIcon icon={Tick02Icon} size={14} color="#00bbff" />
            ) : null}
          </Pressable>
          {projects.map((proj) => {
            const active = projectId === proj.id;
            const color = proj.color ?? "#71717a";
            return (
              <Pressable
                key={proj.id}
                onPress={() => {
                  selectionHaptic();
                  onChangeProjectId(proj.id);
                  setShowProject(false);
                }}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 12,
                  paddingHorizontal: 12,
                  paddingVertical: 10,
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

      <LabelPickerSheet ref={labelPickerRef} onDone={onChangeLabels} />
    </View>
  );
}
