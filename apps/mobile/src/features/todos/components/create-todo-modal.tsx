import { useState } from "react";
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  Cancel01Icon,
  Flag02Icon,
  Folder02Icon,
  Tag01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { impactHaptic, notificationHaptic } from "@/lib/haptics";
import { useResponsive } from "@/lib/responsive";
import { Priority, type Project, type TodoCreate } from "../types/todo-types";

interface CreateTodoModalProps {
  visible: boolean;
  onClose: () => void;
  onCreated: (data: TodoCreate) => void;
  projects?: Project[];
  defaultProjectId?: string;
}

const PRIORITY_OPTIONS: {
  value: Priority;
  label: string;
  color: string;
}[] = [
  { value: Priority.NONE, label: "None", color: "#71717a" },
  { value: Priority.LOW, label: "Low", color: "#eab308" },
  { value: Priority.MEDIUM, label: "Medium", color: "#f97316" },
  { value: Priority.HIGH, label: "High", color: "#ef4444" },
];

function formatDateLabel(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function getTodayIso(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

function getTomorrowIso(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

function getNextWeekIso(): string {
  const d = new Date();
  d.setDate(d.getDate() + 7);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

const QUICK_DATES = [
  { label: "Today", getValue: getTodayIso },
  { label: "Tomorrow", getValue: getTomorrowIso },
  { label: "Next Week", getValue: getNextWeekIso },
];

export function CreateTodoModal({
  visible,
  onClose,
  onCreated,
  projects = [],
  defaultProjectId,
}: CreateTodoModalProps) {
  const { spacing, fontSize } = useResponsive();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<Priority>(Priority.NONE);
  const [dueDate, setDueDate] = useState<string | undefined>(undefined);
  const [selectedProjectId, setSelectedProjectId] = useState<
    string | undefined
  >(defaultProjectId);
  const [labelsText, setLabelsText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!title.trim() || isSubmitting) return;

    const labels = labelsText
      .split(",")
      .map((l) => l.trim())
      .filter(Boolean);

    impactHaptic("medium");
    setIsSubmitting(true);
    try {
      onCreated({
        title: title.trim(),
        description: description.trim() || undefined,
        priority,
        due_date: dueDate,
        labels,
        project_id: selectedProjectId,
      });
      notificationHaptic("success");
      setTitle("");
      setDescription("");
      setPriority(Priority.NONE);
      setDueDate(undefined);
      setSelectedProjectId(defaultProjectId);
      setLabelsText("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    setTitle("");
    setDescription("");
    setPriority(Priority.NONE);
    setDueDate(undefined);
    setSelectedProjectId(defaultProjectId);
    setLabelsText("");
    onClose();
  };

  const canSubmit = !!title.trim() && !isSubmitting;

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={handleClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={{ flex: 1, backgroundColor: "#171920" }}
      >
        {/* Header */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            paddingHorizontal: spacing.md,
            paddingTop: spacing.lg,
            paddingBottom: spacing.md,
            borderBottomWidth: 1,
            borderBottomColor: "rgba(255,255,255,0.07)",
          }}
        >
          <Pressable onPress={handleClose} hitSlop={12}>
            <AppIcon icon={Cancel01Icon} size={20} color="#71717a" />
          </Pressable>

          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "600",
              color: "#f4f4f5",
            }}
          >
            New Task
          </Text>

          <Pressable
            onPress={handleSubmit}
            disabled={!canSubmit}
            hitSlop={12}
            style={{
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: 7,
              backgroundColor: canSubmit
                ? "rgba(22,193,255,0.15)"
                : "rgba(255,255,255,0.03)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "600",
                color: canSubmit ? "#16c1ff" : "#3f3f46",
              }}
            >
              {isSubmitting ? "Adding..." : "Add"}
            </Text>
          </Pressable>
        </View>

        <ScrollView
          contentContainerStyle={{
            padding: spacing.md,
            gap: spacing.lg,
          }}
          keyboardShouldPersistTaps="handled"
        >
          {/* Title input */}
          <View style={{ gap: spacing.xs }}>
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#52525b",
                textTransform: "uppercase",
                letterSpacing: 0.8,
                fontWeight: "500",
              }}
            >
              Title
            </Text>
            <TextInput
              value={title}
              onChangeText={setTitle}
              placeholder="What needs to be done?"
              placeholderTextColor="#3f3f46"
              autoFocus
              style={{
                fontSize: fontSize.base,
                color: "#f4f4f5",
                backgroundColor: "rgba(255,255,255,0.04)",
                borderRadius: 12,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.md,
                borderWidth: 1,
                borderColor: "rgba(255,255,255,0.07)",
              }}
            />
          </View>

          {/* Description input */}
          <View style={{ gap: spacing.xs }}>
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#52525b",
                textTransform: "uppercase",
                letterSpacing: 0.8,
                fontWeight: "500",
              }}
            >
              Description
            </Text>
            <TextInput
              value={description}
              onChangeText={setDescription}
              placeholder="Add details..."
              placeholderTextColor="#3f3f46"
              multiline
              numberOfLines={3}
              textAlignVertical="top"
              style={{
                fontSize: fontSize.sm,
                color: "#f4f4f5",
                backgroundColor: "rgba(255,255,255,0.04)",
                borderRadius: 12,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.md,
                borderWidth: 1,
                borderColor: "rgba(255,255,255,0.07)",
                minHeight: 80,
              }}
            />
          </View>

          {/* Due date selector */}
          <View style={{ gap: spacing.sm }}>
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
            >
              <AppIcon icon={Calendar03Icon} size={14} color="#52525b" />
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#52525b",
                  textTransform: "uppercase",
                  letterSpacing: 0.8,
                  fontWeight: "500",
                }}
              >
                Due Date
              </Text>
            </View>
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              {/* Clear option */}
              <Pressable
                onPress={() => setDueDate(undefined)}
                style={{
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.sm,
                  borderRadius: 8,
                  backgroundColor:
                    dueDate === undefined
                      ? "rgba(22,193,255,0.12)"
                      : "rgba(255,255,255,0.05)",
                  borderWidth: 1,
                  borderColor:
                    dueDate === undefined
                      ? "rgba(22,193,255,0.25)"
                      : "rgba(255,255,255,0.06)",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    fontWeight: dueDate === undefined ? "600" : "400",
                    color: dueDate === undefined ? "#16c1ff" : "#71717a",
                  }}
                >
                  No date
                </Text>
              </Pressable>

              {QUICK_DATES.map((qd) => {
                const val = qd.getValue();
                const isSelected =
                  dueDate !== undefined &&
                  new Date(dueDate).toDateString() ===
                    new Date(val).toDateString();
                return (
                  <Pressable
                    key={qd.label}
                    onPress={() => setDueDate(val)}
                    style={{
                      paddingHorizontal: spacing.md,
                      paddingVertical: spacing.sm,
                      borderRadius: 8,
                      backgroundColor: isSelected
                        ? "rgba(22,193,255,0.12)"
                        : "rgba(255,255,255,0.05)",
                      borderWidth: 1,
                      borderColor: isSelected
                        ? "rgba(22,193,255,0.25)"
                        : "rgba(255,255,255,0.06)",
                    }}
                  >
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        fontWeight: isSelected ? "600" : "400",
                        color: isSelected ? "#16c1ff" : "#71717a",
                      }}
                    >
                      {qd.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            {/* Show selected date label if set and not a quick option */}
            {dueDate !== undefined &&
              !QUICK_DATES.some(
                (qd) =>
                  new Date(qd.getValue()).toDateString() ===
                  new Date(dueDate).toDateString(),
              ) && (
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#16c1ff",
                    fontWeight: "500",
                  }}
                >
                  {formatDateLabel(dueDate)}
                </Text>
              )}
          </View>

          {/* Priority selector */}
          <View style={{ gap: spacing.sm }}>
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
            >
              <AppIcon icon={Flag02Icon} size={14} color="#52525b" />
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#52525b",
                  textTransform: "uppercase",
                  letterSpacing: 0.8,
                  fontWeight: "500",
                }}
              >
                Priority
              </Text>
            </View>
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              {PRIORITY_OPTIONS.map((opt) => {
                const isSelected = priority === opt.value;
                return (
                  <Pressable
                    key={opt.value}
                    onPress={() => setPriority(opt.value)}
                    style={{
                      flex: 1,
                      flexDirection: "row",
                      alignItems: "center",
                      justifyContent: "center",
                      paddingVertical: spacing.sm + 2,
                      borderRadius: 10,
                      backgroundColor: isSelected
                        ? `${opt.color}15`
                        : "rgba(255,255,255,0.04)",
                      borderWidth: 1,
                      borderColor: isSelected
                        ? `${opt.color}35`
                        : "rgba(255,255,255,0.06)",
                      gap: 4,
                    }}
                  >
                    <AppIcon
                      icon={Flag02Icon}
                      size={13}
                      color={isSelected ? opt.color : "#52525b"}
                    />
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        fontWeight: isSelected ? "600" : "400",
                        color: isSelected ? opt.color : "#71717a",
                      }}
                    >
                      {opt.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>

          {/* Project picker */}
          {projects.length > 0 && (
            <View style={{ gap: spacing.sm }}>
              <View
                style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
              >
                <AppIcon icon={Folder02Icon} size={14} color="#52525b" />
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#52525b",
                    textTransform: "uppercase",
                    letterSpacing: 0.8,
                    fontWeight: "500",
                  }}
                >
                  Project
                </Text>
              </View>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ gap: spacing.sm }}
              >
                <Pressable
                  onPress={() => setSelectedProjectId(undefined)}
                  style={{
                    paddingHorizontal: spacing.md,
                    paddingVertical: spacing.sm,
                    borderRadius: 8,
                    backgroundColor:
                      selectedProjectId === undefined
                        ? "rgba(22,193,255,0.12)"
                        : "rgba(255,255,255,0.05)",
                    borderWidth: 1,
                    borderColor:
                      selectedProjectId === undefined
                        ? "rgba(22,193,255,0.25)"
                        : "rgba(255,255,255,0.06)",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      fontWeight:
                        selectedProjectId === undefined ? "600" : "400",
                      color:
                        selectedProjectId === undefined ? "#16c1ff" : "#71717a",
                    }}
                  >
                    None
                  </Text>
                </Pressable>
                {projects.map((project) => {
                  const isSelected = selectedProjectId === project.id;
                  const chipColor = project.color ?? "#71717a";
                  return (
                    <Pressable
                      key={project.id}
                      onPress={() => setSelectedProjectId(project.id)}
                      style={{
                        flexDirection: "row",
                        alignItems: "center",
                        gap: 5,
                        paddingHorizontal: spacing.md,
                        paddingVertical: spacing.sm,
                        borderRadius: 8,
                        backgroundColor: isSelected
                          ? `${chipColor}20`
                          : "rgba(255,255,255,0.05)",
                        borderWidth: 1,
                        borderColor: isSelected
                          ? `${chipColor}40`
                          : "rgba(255,255,255,0.06)",
                      }}
                    >
                      <AppIcon
                        icon={Folder02Icon}
                        size={12}
                        color={isSelected ? chipColor : "#52525b"}
                      />
                      <Text
                        style={{
                          fontSize: fontSize.xs,
                          fontWeight: isSelected ? "600" : "400",
                          color: isSelected ? chipColor : "#71717a",
                        }}
                      >
                        {project.name}
                      </Text>
                    </Pressable>
                  );
                })}
              </ScrollView>
            </View>
          )}

          {/* Labels input */}
          <View style={{ gap: spacing.xs }}>
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
            >
              <AppIcon icon={Tag01Icon} size={14} color="#52525b" />
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#52525b",
                  textTransform: "uppercase",
                  letterSpacing: 0.8,
                  fontWeight: "500",
                }}
              >
                Labels
              </Text>
            </View>
            <TextInput
              value={labelsText}
              onChangeText={setLabelsText}
              placeholder="work, personal, urgent..."
              placeholderTextColor="#3f3f46"
              style={{
                fontSize: fontSize.sm,
                color: "#f4f4f5",
                backgroundColor: "rgba(255,255,255,0.04)",
                borderRadius: 12,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.md,
                borderWidth: 1,
                borderColor: "rgba(255,255,255,0.07)",
              }}
            />
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#3f3f46",
              }}
            >
              Separate multiple labels with commas
            </Text>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
}
