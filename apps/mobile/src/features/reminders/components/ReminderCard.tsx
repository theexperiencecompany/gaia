import * as Haptics from "expo-haptics";
import { useCallback, useRef } from "react";
import { Alert, type Animated, Pressable, View } from "react-native";
import { Swipeable } from "react-native-gesture-handler";
import {
  Clock01Icon,
  Delete02Icon,
  Notification02Icon,
  PlayIcon,
  ToggleOffIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Reminder } from "../api/reminders-api";

const DAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

const SHORT_MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function formatTime(hour: number, minute: number): string {
  const period = hour >= 12 ? "PM" : "AM";
  const displayHour = hour > 12 ? hour - 12 : hour === 0 ? 12 : hour;
  return `${displayHour}:${String(minute).padStart(2, "0")} ${period}`;
}

export function parseCronToHuman(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;

  const [minuteStr, hourStr, domStr, , dowStr] = parts;

  const minute = minuteStr === "*" ? 0 : Number.parseInt(minuteStr, 10);
  const hour = hourStr === "*" ? 0 : Number.parseInt(hourStr, 10);

  // Every hour: "0 * * * *"
  if (hourStr === "*" && domStr === "*" && dowStr === "*") {
    return "Every hour";
  }

  // Every day at time: "M H * * *"
  if (
    domStr === "*" &&
    dowStr === "*" &&
    hourStr !== "*" &&
    minuteStr !== "*"
  ) {
    return `Every day at ${formatTime(hour, minute)}`;
  }

  // Every weekday: "M H * * 1-5"
  if (domStr === "*" && dowStr === "1-5") {
    return `Weekdays at ${formatTime(hour, minute)}`;
  }

  // Weekly on a specific day: "M H * * D"
  if (
    domStr === "*" &&
    dowStr !== "*" &&
    !dowStr.includes(",") &&
    !dowStr.includes("-") &&
    !dowStr.includes("/")
  ) {
    const dayIndex = Number.parseInt(dowStr, 10);
    if (dayIndex >= 0 && dayIndex <= 6) {
      return `Every ${DAYS[dayIndex]} at ${formatTime(hour, minute)}`;
    }
  }

  // Monthly on a day: "M H D * *"
  if (
    domStr !== "*" &&
    !domStr.includes(",") &&
    !domStr.includes("-") &&
    dowStr === "*"
  ) {
    const dom = Number.parseInt(domStr, 10);
    const suffix =
      dom === 1 || dom === 21 || dom === 31
        ? "st"
        : dom === 2 || dom === 22
          ? "nd"
          : dom === 3 || dom === 23
            ? "rd"
            : "th";
    return `Monthly on the ${dom}${suffix} at ${formatTime(hour, minute)}`;
  }

  return cron;
}

function formatNextRun(nextRun?: string): string {
  if (!nextRun) return "Not scheduled";

  const date = new Date(nextRun);
  if (Number.isNaN(date.getTime())) return "Not scheduled";

  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffMins = Math.round(diffMs / 60000);
  const diffHours = Math.round(diffMs / 3600000);
  const diffDays = Math.round(diffMs / 86400000);

  if (diffMins < 1) return "Due now";
  if (diffMins < 60) return `In ${diffMins}m`;
  if (diffHours < 24) return `In ${diffHours}h`;
  if (diffDays === 1) return "Tomorrow";
  if (diffDays < 7) return `In ${diffDays} days`;

  return `${SHORT_MONTHS[date.getMonth()]} ${date.getDate()}`;
}

interface ReminderCardProps {
  reminder: Reminder;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onDelete: (id: string) => void;
  isActionLoading?: boolean;
}

export function ReminderCard({
  reminder,
  onPause,
  onResume,
  onDelete,
  isActionLoading = false,
}: ReminderCardProps) {
  const { spacing, fontSize } = useResponsive();
  const swipeableRef = useRef<Swipeable>(null);

  const isActive = reminder.status === "active";

  const handleTogglePause = useCallback(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    if (isActive) {
      onPause(reminder.id);
    } else {
      onResume(reminder.id);
    }
  }, [isActive, reminder.id, onPause, onResume]);

  const handleDelete = useCallback(() => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    swipeableRef.current?.close();
    Alert.alert(
      "Delete Reminder",
      `Delete "${reminder.title}"? This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => onDelete(reminder.id),
        },
      ],
    );
  }, [reminder.id, reminder.title, onDelete]);

  const renderRightActions = useCallback(
    (_progress: Animated.AnimatedInterpolation<number>) => {
      return (
        <Pressable
          onPress={handleDelete}
          style={{
            backgroundColor: "#ef4444",
            justifyContent: "center",
            alignItems: "center",
            width: 72,
            marginLeft: spacing.sm,
            borderRadius: 14,
          }}
        >
          <Delete02Icon size={20} color="#fff" />
        </Pressable>
      );
    },
    [handleDelete, spacing.sm],
  );

  const scheduleText = parseCronToHuman(reminder.cron_expression);
  const nextRunText = formatNextRun(reminder.next_run);

  return (
    <Swipeable
      ref={swipeableRef}
      renderRightActions={renderRightActions}
      rightThreshold={40}
      overshootRight={false}
    >
      <View
        style={{
          backgroundColor: "#131416",
          borderRadius: 14,
          padding: spacing.md,
          borderWidth: 1,
          borderColor: isActive
            ? "rgba(22,193,255,0.12)"
            : "rgba(255,255,255,0.06)",
          gap: spacing.xs,
        }}
      >
        {/* Title row */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: spacing.sm,
          }}
        >
          <View style={{ flex: 1, gap: 2 }}>
            <Text
              style={{
                fontSize: fontSize.base,
                fontWeight: "600",
                color: isActive ? "#e8ebef" : "#71717a",
              }}
              numberOfLines={2}
            >
              {reminder.title}
            </Text>
            {!!reminder.description && (
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#71717a",
                  lineHeight: fontSize.sm * 1.4,
                }}
                numberOfLines={2}
              >
                {reminder.description}
              </Text>
            )}
          </View>

          {/* Status badge */}
          <View
            style={{
              paddingHorizontal: spacing.sm,
              paddingVertical: 3,
              borderRadius: 20,
              backgroundColor: isActive
                ? "rgba(34,197,94,0.12)"
                : "rgba(113,113,122,0.12)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                fontWeight: "600",
                color: isActive ? "#22c55e" : "#71717a",
              }}
            >
              {isActive ? "Active" : "Paused"}
            </Text>
          </View>
        </View>

        {/* Schedule + next run row */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            gap: spacing.sm,
            marginTop: spacing.xs,
          }}
        >
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.xs,
              flex: 1,
            }}
          >
            <Notification02Icon size={13} color="#52525b" />
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#52525b",
              }}
              numberOfLines={1}
            >
              {scheduleText}
            </Text>
          </View>

          {isActive && (
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 4,
              }}
            >
              <Clock01Icon size={12} color="#16c1ff" />
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#16c1ff",
                }}
              >
                {nextRunText}
              </Text>
            </View>
          )}
        </View>

        {/* Pause/resume button */}
        <Pressable
          onPress={handleTogglePause}
          disabled={isActionLoading}
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "center",
            gap: spacing.xs,
            marginTop: spacing.xs,
            paddingVertical: spacing.sm,
            borderRadius: 10,
            backgroundColor: isActive
              ? "rgba(255,255,255,0.05)"
              : "rgba(22,193,255,0.08)",
            opacity: isActionLoading ? 0.5 : 1,
          }}
        >
          {isActive ? (
            <ToggleOffIcon size={14} color="#a1a1aa" />
          ) : (
            <PlayIcon size={14} color="#16c1ff" />
          )}
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "500",
              color: isActive ? "#a1a1aa" : "#16c1ff",
            }}
          >
            {isActive ? "Pause" : "Resume"}
          </Text>
        </Pressable>
      </View>
    </Swipeable>
  );
}
