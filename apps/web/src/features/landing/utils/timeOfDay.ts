export type TimeOfDay = "morning" | "day" | "evening" | "night";

export function getTimeOfDay(timezone?: string): TimeOfDay {
  const hour = timezone
    ? new Date(
        new Date().toLocaleString("en-US", { timeZone: timezone }),
      ).getHours()
    : new Date().getHours();
  if (hour >= 6 && hour < 12) return "morning";
  if (hour >= 12 && hour < 19) return "day";
  if (hour >= 19 && hour < 21) return "evening";
  return "night";
}

export function isDarkTimeOfDay(time: TimeOfDay): boolean {
  return time === "night" || time === "evening";
}

const TIME_OF_DAY_CYCLE: readonly TimeOfDay[] = [
  "morning",
  "day",
  "evening",
  "night",
];

export function getNextTimeOfDay(current: TimeOfDay): TimeOfDay {
  const idx = TIME_OF_DAY_CYCLE.indexOf(current);
  return TIME_OF_DAY_CYCLE[(idx + 1) % TIME_OF_DAY_CYCLE.length];
}
