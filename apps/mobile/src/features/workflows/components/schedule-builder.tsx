import { Pressable, ScrollView, TextInput, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

export interface ScheduleConfig {
  preset: "hourly" | "daily" | "weekly" | "monthly" | "custom";
  hour?: number;
  minute?: number;
  dayOfWeek?: number;
  dayOfMonth?: number;
  customCron?: string;
}

interface ScheduleBuilderProps {
  value: ScheduleConfig;
  onChange: (config: ScheduleConfig) => void;
}

const PRESETS: {
  id: ScheduleConfig["preset"];
  label: string;
}[] = [
  { id: "hourly", label: "Every hour" },
  { id: "daily", label: "Every day" },
  { id: "weekly", label: "Every week" },
  { id: "monthly", label: "Every month" },
  { id: "custom", label: "Custom (cron)" },
];

const DAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

function describeCron(config: ScheduleConfig): string {
  switch (config.preset) {
    case "hourly":
      return "Runs every hour";
    case "daily": {
      const h = config.hour ?? 9;
      const m = config.minute ?? 0;
      const period = h >= 12 ? "PM" : "AM";
      const displayH = h > 12 ? h - 12 : h === 0 ? 12 : h;
      return `Runs daily at ${displayH}:${String(m).padStart(2, "0")} ${period}`;
    }
    case "weekly": {
      const day = DAYS[config.dayOfWeek ?? 1];
      const h = config.hour ?? 9;
      const period = h >= 12 ? "PM" : "AM";
      const displayH = h > 12 ? h - 12 : h === 0 ? 12 : h;
      return `Runs every ${day} at ${displayH}:00 ${period}`;
    }
    case "monthly":
      return `Runs on day ${config.dayOfMonth ?? 1} of each month`;
    case "custom":
      return config.customCron
        ? `Cron: ${config.customCron}`
        : "Enter a cron expression";
    default:
      return "";
  }
}

export function toCronExpression(config: ScheduleConfig): string {
  const m = config.minute ?? 0;
  const h = config.hour ?? 9;
  switch (config.preset) {
    case "hourly":
      return "0 * * * *";
    case "daily":
      return `${m} ${h} * * *`;
    case "weekly":
      return `${m} ${h} * * ${config.dayOfWeek ?? 1}`;
    case "monthly":
      return `${m} ${h} ${config.dayOfMonth ?? 1} * *`;
    case "custom":
      return config.customCron ?? "";
    default:
      return "";
  }
}

interface TimePickerRowProps {
  hour: number;
  minute: number;
  onChange: (h: number, m: number) => void;
}

function TimePickerRow({ hour, minute, onChange }: TimePickerRowProps) {
  const { spacing, fontSize } = useResponsive();
  const displayH = hour > 12 ? hour - 12 : hour === 0 ? 12 : hour;
  const isPM = hour >= 12;

  const cycleHour = (dir: 1 | -1) => {
    const newH = (hour + dir + 24) % 24;
    onChange(newH, minute);
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
      style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}
    >
      <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>Time:</Text>
      <Pressable onPress={() => cycleHour(-1)} hitSlop={8}>
        <Text style={{ color: "#00bbff", fontSize: fontSize.md }}>‹</Text>
      </Pressable>
      <Text
        style={{
          color: "#fff",
          fontSize: fontSize.sm,
          minWidth: 20,
          textAlign: "center",
        }}
      >
        {displayH}
      </Text>
      <Pressable onPress={() => cycleHour(1)} hitSlop={8}>
        <Text style={{ color: "#00bbff", fontSize: fontSize.md }}>›</Text>
      </Pressable>
      <Text style={{ color: "#71717a" }}>:</Text>
      <Pressable onPress={cycleMinute} hitSlop={8}>
        <Text style={{ color: "#fff", fontSize: fontSize.sm }}>
          {String(minute).padStart(2, "0")}
        </Text>
      </Pressable>
      <Pressable
        onPress={toggleAMPM}
        style={{
          paddingHorizontal: spacing.sm,
          paddingVertical: 2,
          backgroundColor: "#3f3f46",
          borderRadius: 6,
        }}
      >
        <Text style={{ color: "#a1a1aa", fontSize: fontSize.xs }}>
          {isPM ? "PM" : "AM"}
        </Text>
      </Pressable>
    </View>
  );
}

export function ScheduleBuilder({ value, onChange }: ScheduleBuilderProps) {
  const { spacing, fontSize } = useResponsive();

  return (
    <View style={{ gap: spacing.md }}>
      {/* Preset chips */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          {PRESETS.map((preset) => (
            <Pressable
              key={preset.id}
              onPress={() => onChange({ ...value, preset: preset.id })}
              style={{
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm,
                borderRadius: 20,
                borderWidth: 1,
                borderColor:
                  value.preset === preset.id
                    ? "#00bbff"
                    : "rgba(255,255,255,0.1)",
                backgroundColor:
                  value.preset === preset.id
                    ? "rgba(0,187,255,0.1)"
                    : "transparent",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: value.preset === preset.id ? "#00bbff" : "#a1a1aa",
                }}
              >
                {preset.label}
              </Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>

      {/* Time picker for daily / weekly / monthly */}
      {(value.preset === "daily" ||
        value.preset === "weekly" ||
        value.preset === "monthly") && (
        <TimePickerRow
          hour={value.hour ?? 9}
          minute={value.minute ?? 0}
          onChange={(h, m) => onChange({ ...value, hour: h, minute: m })}
        />
      )}

      {/* Day of week for weekly */}
      {value.preset === "weekly" && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={{ flexDirection: "row", gap: spacing.xs }}>
            {DAYS.map((day, i) => (
              <Pressable
                key={day}
                onPress={() => onChange({ ...value, dayOfWeek: i })}
                style={{
                  paddingHorizontal: spacing.sm + 2,
                  paddingVertical: spacing.xs + 2,
                  borderRadius: 8,
                  borderWidth: 1,
                  borderColor:
                    (value.dayOfWeek ?? 1) === i
                      ? "#00bbff"
                      : "rgba(255,255,255,0.1)",
                  backgroundColor:
                    (value.dayOfWeek ?? 1) === i
                      ? "rgba(0,187,255,0.1)"
                      : "transparent",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: (value.dayOfWeek ?? 1) === i ? "#00bbff" : "#a1a1aa",
                  }}
                >
                  {day.slice(0, 3)}
                </Text>
              </Pressable>
            ))}
          </View>
        </ScrollView>
      )}

      {/* Day of month for monthly */}
      {value.preset === "monthly" && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
          }}
        >
          <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
            Day of month:
          </Text>
          {[1, 5, 10, 15, 20, 25].map((day) => (
            <Pressable
              key={day}
              onPress={() => onChange({ ...value, dayOfMonth: day })}
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                alignItems: "center",
                justifyContent: "center",
                borderWidth: 1,
                borderColor:
                  (value.dayOfMonth ?? 1) === day
                    ? "#00bbff"
                    : "rgba(255,255,255,0.1)",
                backgroundColor:
                  (value.dayOfMonth ?? 1) === day
                    ? "rgba(0,187,255,0.1)"
                    : "transparent",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color:
                    (value.dayOfMonth ?? 1) === day ? "#00bbff" : "#a1a1aa",
                }}
              >
                {day}
              </Text>
            </Pressable>
          ))}
        </View>
      )}

      {/* Custom cron expression input */}
      {value.preset === "custom" && (
        <View style={{ gap: spacing.xs }}>
          <TextInput
            value={value.customCron ?? ""}
            onChangeText={(t) => onChange({ ...value, customCron: t })}
            placeholder="e.g. 0 9 * * 1"
            placeholderTextColor="#52525b"
            style={{
              borderWidth: 1,
              borderColor: "#3f3f46",
              borderRadius: 10,
              padding: spacing.md,
              color: "#fff",
              fontSize: fontSize.sm,
              backgroundColor: "#2c2c2e",
              fontFamily: "monospace",
            }}
          />
          <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
            Format: minute hour day month weekday
          </Text>
        </View>
      )}

      {/* Human-readable description */}
      <View
        style={{
          backgroundColor: "rgba(0,187,255,0.05)",
          borderRadius: 10,
          padding: spacing.sm + 2,
          borderWidth: 1,
          borderColor: "rgba(0,187,255,0.15)",
        }}
      >
        <Text style={{ fontSize: fontSize.xs, color: "#00bbff" }}>
          {describeCron(value)}
        </Text>
      </View>
    </View>
  );
}
