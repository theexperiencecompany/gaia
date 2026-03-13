import { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Cancel01Icon, CheckmarkCircle02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { impactHaptic, notificationHaptic } from "@/lib/haptics";
import { useResponsive } from "@/lib/responsive";
import type { ReminderCreate } from "../api/reminders-api";

function getUserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

type SchedulePreset = "daily" | "weekly" | "monthly" | "custom";

interface ScheduleState {
  preset: SchedulePreset;
  hour: number;
  minute: number;
  dayOfWeek: number;
  dayOfMonth: number;
  customCron: string;
}

const PRESETS: { id: SchedulePreset; label: string }[] = [
  { id: "daily", label: "Daily" },
  { id: "weekly", label: "Weekly" },
  { id: "monthly", label: "Monthly" },
  { id: "custom", label: "Custom" },
];

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function toCronExpression(s: ScheduleState): string {
  const m = s.minute;
  const h = s.hour;
  switch (s.preset) {
    case "daily":
      return `${m} ${h} * * *`;
    case "weekly":
      return `${m} ${h} * * ${s.dayOfWeek}`;
    case "monthly":
      return `${m} ${h} ${s.dayOfMonth} * *`;
    case "custom":
      return s.customCron;
    default:
      return `${m} ${h} * * *`;
  }
}

function formatTimeLabel(hour: number, minute: number): string {
  const period = hour >= 12 ? "PM" : "AM";
  const displayHour = hour > 12 ? hour - 12 : hour === 0 ? 12 : hour;
  return `${displayHour}:${String(minute).padStart(2, "0")} ${period}`;
}

interface TimePickerRowProps {
  hour: number;
  minute: number;
  onChange: (h: number, m: number) => void;
  spacing: { xs: number; sm: number; md: number };
  fontSize: { xs: number; sm: number; md: number };
}

function TimePickerRow({
  hour,
  minute,
  onChange,
  spacing,
  fontSize,
}: TimePickerRowProps) {
  const displayHour = hour > 12 ? hour - 12 : hour === 0 ? 12 : hour;
  const isPM = hour >= 12;

  const cycleHour = (dir: 1 | -1) => {
    onChange((hour + dir + 24) % 24, minute);
  };

  const cycleMinute = () => {
    const steps = [0, 15, 30, 45];
    const idx = steps.indexOf(minute);
    onChange(hour, steps[(idx + 1) % steps.length]);
  };

  const toggleAMPM = () => {
    onChange(isPM ? hour - 12 : hour + 12, minute);
  };

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.sm,
        backgroundColor: "#1c1c1e",
        borderRadius: 10,
        padding: spacing.md,
      }}
    >
      <Text style={{ fontSize: fontSize.sm, color: "#71717a", flex: 1 }}>
        Time
      </Text>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Pressable onPress={() => cycleHour(-1)} hitSlop={12}>
          <Text
            style={{
              color: "#16c1ff",
              fontSize: fontSize.md + 4,
              fontWeight: "300",
            }}
          >
            ‹
          </Text>
        </Pressable>
        <Text
          style={{
            color: "#e8ebef",
            fontSize: fontSize.md,
            fontWeight: "600",
            minWidth: 36,
            textAlign: "center",
          }}
        >
          {displayHour}:{String(minute).padStart(2, "0")}
        </Text>
        <Pressable onPress={() => cycleHour(1)} hitSlop={12}>
          <Text
            style={{
              color: "#16c1ff",
              fontSize: fontSize.md + 4,
              fontWeight: "300",
            }}
          >
            ›
          </Text>
        </Pressable>
        <Pressable onPress={cycleMinute} hitSlop={12} style={{ marginLeft: 4 }}>
          <View
            style={{
              backgroundColor: "#3f3f46",
              borderRadius: 6,
              paddingHorizontal: 8,
              paddingVertical: 3,
            }}
          >
            <Text style={{ color: "#a1a1aa", fontSize: fontSize.xs }}>
              {String(minute).padStart(2, "0")}m
            </Text>
          </View>
        </Pressable>
        <Pressable onPress={toggleAMPM} hitSlop={12}>
          <View
            style={{
              backgroundColor: "#3f3f46",
              borderRadius: 6,
              paddingHorizontal: 8,
              paddingVertical: 3,
            }}
          >
            <Text style={{ color: "#a1a1aa", fontSize: fontSize.xs }}>
              {isPM ? "PM" : "AM"}
            </Text>
          </View>
        </Pressable>
      </View>
    </View>
  );
}

interface CreateReminderSheetProps {
  visible: boolean;
  onClose: () => void;
  onCreated: (data: ReminderCreate) => Promise<unknown>;
  isSubmitting?: boolean;
}

export function CreateReminderSheet({
  visible,
  onClose,
  onCreated,
  isSubmitting = false,
}: CreateReminderSheetProps) {
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const slideAnim = useRef(new Animated.Value(600)).current;

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [schedule, setSchedule] = useState<ScheduleState>({
    preset: "daily",
    hour: 9,
    minute: 0,
    dayOfWeek: 1,
    dayOfMonth: 1,
    customCron: "",
  });

  const timezone = getUserTimezone();

  useEffect(() => {
    if (visible) {
      Animated.spring(slideAnim, {
        toValue: 0,
        useNativeDriver: true,
        damping: 20,
        stiffness: 200,
      }).start();
    } else {
      Animated.timing(slideAnim, {
        toValue: 600,
        duration: 250,
        useNativeDriver: true,
      }).start();
    }
  }, [visible, slideAnim]);

  const handleClose = useCallback(() => {
    setTitle("");
    setDescription("");
    setSchedule({
      preset: "daily",
      hour: 9,
      minute: 0,
      dayOfWeek: 1,
      dayOfMonth: 1,
      customCron: "",
    });
    onClose();
  }, [onClose]);

  const handleCreate = useCallback(async () => {
    if (!title.trim()) return;

    const cronExpression = toCronExpression(schedule);
    if (!cronExpression.trim()) return;

    impactHaptic("medium");

    await onCreated({
      title: title.trim(),
      description: description.trim() || undefined,
      cronExpression,
      timezone,
    });

    notificationHaptic("success");
    handleClose();
  }, [title, description, schedule, timezone, onCreated, handleClose]);

  const canSubmit = title.trim().length > 0 && !isSubmitting;

  const schedulePreviewLabel = (() => {
    const h = schedule.hour;
    const m = schedule.minute;
    switch (schedule.preset) {
      case "daily":
        return `Every day at ${formatTimeLabel(h, m)}`;
      case "weekly":
        return `Every ${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][schedule.dayOfWeek]} at ${formatTimeLabel(h, m)}`;
      case "monthly":
        return `Monthly on day ${schedule.dayOfMonth} at ${formatTimeLabel(h, m)}`;
      case "custom":
        return schedule.customCron || "Enter a cron expression";
      default:
        return "";
    }
  })();

  return (
    <Modal
      visible={visible}
      transparent
      animationType="none"
      onRequestClose={handleClose}
    >
      <Pressable
        style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.6)" }}
        onPress={handleClose}
      />
      <Animated.View
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          transform: [{ translateY: slideAnim }],
          backgroundColor: "#0f0f0f",
          borderTopLeftRadius: 24,
          borderTopRightRadius: 24,
          borderTopWidth: 1,
          borderTopColor: "rgba(255,255,255,0.08)",
        }}
      >
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
        >
          <ScrollView
            showsVerticalScrollIndicator={false}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={{
              paddingHorizontal: spacing.md,
              paddingTop: spacing.lg,
              paddingBottom: insets.bottom + spacing.lg,
              gap: spacing.md,
            }}
          >
            {/* Header */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.lg,
                  fontWeight: "700",
                  color: "#e8ebef",
                }}
              >
                New Reminder
              </Text>
              <Pressable
                onPress={handleClose}
                hitSlop={10}
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 16,
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor: "rgba(255,255,255,0.06)",
                }}
              >
                <Cancel01Icon size={16} color="#71717a" />
              </Pressable>
            </View>

            {/* Title input */}
            <View style={{ gap: spacing.xs }}>
              <Text style={{ fontSize: fontSize.sm, color: "#71717a" }}>
                Title *
              </Text>
              <TextInput
                value={title}
                onChangeText={setTitle}
                placeholder="Remind me to..."
                placeholderTextColor="#3f3f46"
                style={{
                  backgroundColor: "#1c1c1e",
                  borderRadius: 12,
                  padding: spacing.md,
                  fontSize: fontSize.base,
                  color: "#e8ebef",
                  borderWidth: 1,
                  borderColor: title.trim()
                    ? "rgba(22,193,255,0.2)"
                    : "#27272a",
                }}
              />
            </View>

            {/* Description input */}
            <View style={{ gap: spacing.xs }}>
              <Text style={{ fontSize: fontSize.sm, color: "#71717a" }}>
                Description (optional)
              </Text>
              <TextInput
                value={description}
                onChangeText={setDescription}
                placeholder="Add a note..."
                placeholderTextColor="#3f3f46"
                multiline
                numberOfLines={2}
                style={{
                  backgroundColor: "#1c1c1e",
                  borderRadius: 12,
                  padding: spacing.md,
                  fontSize: fontSize.base,
                  color: "#e8ebef",
                  borderWidth: 1,
                  borderColor: "#27272a",
                  textAlignVertical: "top",
                  minHeight: 72,
                }}
              />
            </View>

            {/* Schedule section */}
            <View style={{ gap: spacing.sm }}>
              <Text style={{ fontSize: fontSize.sm, color: "#71717a" }}>
                Schedule
              </Text>

              {/* Preset chips */}
              <View
                style={{
                  flexDirection: "row",
                  gap: spacing.sm,
                  flexWrap: "wrap",
                }}
              >
                {PRESETS.map((preset) => {
                  const isSelected = schedule.preset === preset.id;
                  return (
                    <Pressable
                      key={preset.id}
                      onPress={() =>
                        setSchedule((prev) => ({
                          ...prev,
                          preset: preset.id,
                        }))
                      }
                      style={{
                        paddingHorizontal: spacing.md,
                        paddingVertical: spacing.sm,
                        borderRadius: 20,
                        borderWidth: 1,
                        borderColor: isSelected
                          ? "#16c1ff"
                          : "rgba(255,255,255,0.1)",
                        backgroundColor: isSelected
                          ? "rgba(22,193,255,0.1)"
                          : "transparent",
                      }}
                    >
                      <Text
                        style={{
                          fontSize: fontSize.sm,
                          fontWeight: isSelected ? "600" : "400",
                          color: isSelected ? "#16c1ff" : "#a1a1aa",
                        }}
                      >
                        {preset.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>

              {/* Time picker */}
              {schedule.preset !== "custom" && (
                <TimePickerRow
                  hour={schedule.hour}
                  minute={schedule.minute}
                  onChange={(h, m) =>
                    setSchedule((prev) => ({
                      ...prev,
                      hour: h,
                      minute: m,
                    }))
                  }
                  spacing={spacing}
                  fontSize={fontSize}
                />
              )}

              {/* Day of week picker */}
              {schedule.preset === "weekly" && (
                <View
                  style={{
                    flexDirection: "row",
                    gap: spacing.xs,
                    flexWrap: "wrap",
                  }}
                >
                  {DAYS.map((day, i) => {
                    const isSelected = schedule.dayOfWeek === i;
                    return (
                      <Pressable
                        key={day}
                        onPress={() =>
                          setSchedule((prev) => ({
                            ...prev,
                            dayOfWeek: i,
                          }))
                        }
                        style={{
                          width: 40,
                          height: 40,
                          borderRadius: 20,
                          alignItems: "center",
                          justifyContent: "center",
                          borderWidth: 1,
                          borderColor: isSelected
                            ? "#16c1ff"
                            : "rgba(255,255,255,0.1)",
                          backgroundColor: isSelected
                            ? "rgba(22,193,255,0.1)"
                            : "transparent",
                        }}
                      >
                        <Text
                          style={{
                            fontSize: fontSize.xs,
                            fontWeight: isSelected ? "600" : "400",
                            color: isSelected ? "#16c1ff" : "#a1a1aa",
                          }}
                        >
                          {day}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              )}

              {/* Day of month picker */}
              {schedule.preset === "monthly" && (
                <View
                  style={{
                    flexDirection: "row",
                    gap: spacing.xs,
                    flexWrap: "wrap",
                  }}
                >
                  {[1, 5, 10, 15, 20, 25, 28].map((day) => {
                    const isSelected = schedule.dayOfMonth === day;
                    return (
                      <Pressable
                        key={day}
                        onPress={() =>
                          setSchedule((prev) => ({
                            ...prev,
                            dayOfMonth: day,
                          }))
                        }
                        style={{
                          width: 40,
                          height: 40,
                          borderRadius: 10,
                          alignItems: "center",
                          justifyContent: "center",
                          borderWidth: 1,
                          borderColor: isSelected
                            ? "#16c1ff"
                            : "rgba(255,255,255,0.1)",
                          backgroundColor: isSelected
                            ? "rgba(22,193,255,0.1)"
                            : "transparent",
                        }}
                      >
                        <Text
                          style={{
                            fontSize: fontSize.sm,
                            fontWeight: isSelected ? "600" : "400",
                            color: isSelected ? "#16c1ff" : "#a1a1aa",
                          }}
                        >
                          {day}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              )}

              {/* Custom cron input */}
              {schedule.preset === "custom" && (
                <View style={{ gap: spacing.xs }}>
                  <TextInput
                    value={schedule.customCron}
                    onChangeText={(text) =>
                      setSchedule((prev) => ({
                        ...prev,
                        customCron: text,
                      }))
                    }
                    placeholder="e.g. 0 9 * * 1"
                    placeholderTextColor="#3f3f46"
                    autoCapitalize="none"
                    autoCorrect={false}
                    style={{
                      backgroundColor: "#1c1c1e",
                      borderRadius: 12,
                      padding: spacing.md,
                      fontSize: fontSize.base,
                      color: "#e8ebef",
                      borderWidth: 1,
                      borderColor: "#27272a",
                      fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
                    }}
                  />
                  <Text style={{ fontSize: fontSize.xs, color: "#3f3f46" }}>
                    Format: minute hour day month weekday
                  </Text>
                </View>
              )}

              {/* Schedule preview */}
              <View
                style={{
                  backgroundColor: "rgba(22,193,255,0.05)",
                  borderRadius: 10,
                  padding: spacing.md,
                  borderWidth: 1,
                  borderColor: "rgba(22,193,255,0.12)",
                }}
              >
                <Text style={{ fontSize: fontSize.sm, color: "#16c1ff" }}>
                  {schedulePreviewLabel}
                </Text>
              </View>
            </View>

            {/* Timezone display */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.xs,
                opacity: 0.5,
              }}
            >
              <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                Timezone:
              </Text>
              <Text style={{ fontSize: fontSize.xs, color: "#a1a1aa" }}>
                {timezone}
              </Text>
            </View>

            {/* Create button */}
            <Pressable
              onPress={() => {
                void handleCreate();
              }}
              disabled={!canSubmit}
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                gap: spacing.sm,
                backgroundColor: canSubmit ? "#16c1ff" : "#27272a",
                borderRadius: 14,
                paddingVertical: spacing.md,
                opacity: canSubmit ? 1 : 0.5,
              }}
            >
              <CheckmarkCircle02Icon
                size={18}
                color={canSubmit ? "#000" : "#52525b"}
              />
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "700",
                  color: canSubmit ? "#000" : "#52525b",
                }}
              >
                {isSubmitting ? "Creating..." : "Create Reminder"}
              </Text>
            </Pressable>
          </ScrollView>
        </KeyboardAvoidingView>
      </Animated.View>
    </Modal>
  );
}
