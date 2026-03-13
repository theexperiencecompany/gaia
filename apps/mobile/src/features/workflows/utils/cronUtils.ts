export interface CronSchedule {
  type: "daily" | "weekly" | "monthly" | "custom";
  minute?: number;
  hour?: number;
  dayOfWeek?: number;
  dayOfMonth?: number;
  customExpression?: string;
}

export const buildCronExpression = (schedule: CronSchedule): string => {
  const { type, minute = 0, hour = 9, dayOfWeek, dayOfMonth } = schedule;

  switch (type) {
    case "daily":
      return `${minute} ${hour} * * *`;
    case "weekly":
      return `${minute} ${hour} * * ${dayOfWeek ?? 1}`;
    case "monthly":
      return `${minute} ${hour} ${dayOfMonth ?? 1} * *`;
    case "custom":
      return schedule.customExpression || "0 9 * * *";
    default:
      return "0 9 * * *";
  }
};

export const parseCronExpression = (cron: string): CronSchedule => {
  const parts = cron.split(" ");
  if (parts.length !== 5) {
    return { type: "custom", customExpression: cron };
  }

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;
  const isSimpleInt = (s: string) => /^\d+$/.test(s);

  if (
    isSimpleInt(minute) &&
    isSimpleInt(hour) &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return {
      type: "daily",
      minute: parseInt(minute, 10),
      hour: parseInt(hour, 10),
    };
  }

  if (
    isSimpleInt(minute) &&
    isSimpleInt(hour) &&
    dayOfMonth === "*" &&
    month === "*" &&
    isSimpleInt(dayOfWeek)
  ) {
    return {
      type: "weekly",
      minute: parseInt(minute, 10),
      hour: parseInt(hour, 10),
      dayOfWeek: parseInt(dayOfWeek, 10),
    };
  }

  if (
    isSimpleInt(minute) &&
    isSimpleInt(hour) &&
    isSimpleInt(dayOfMonth) &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return {
      type: "monthly",
      minute: parseInt(minute, 10),
      hour: parseInt(hour, 10),
      dayOfMonth: parseInt(dayOfMonth, 10),
    };
  }

  return { type: "custom", customExpression: cron };
};

const DAY_NAMES = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

const ordinalSuffix = (n: number): string => {
  if (n >= 11 && n <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
};

const formatTime = (hour: number, minute: number): string => {
  const ampm = hour >= 12 ? "PM" : "AM";
  const displayHour = hour > 12 ? hour - 12 : hour === 0 ? 12 : hour;
  const displayMinute = minute.toString().padStart(2, "0");
  return `${displayHour}:${displayMinute} ${ampm}`;
};

export const cronToHumanReadable = (expression: string): string => {
  if (!expression.trim()) return "No schedule set";

  const schedule = parseCronExpression(expression);

  switch (schedule.type) {
    case "daily":
      return `Every day at ${formatTime(schedule.hour!, schedule.minute!)}`;

    case "weekly": {
      const parts = expression.split(" ");
      const dowPart = parts[4];
      if (dowPart.includes(",")) {
        const dayNums = dowPart
          .split(",")
          .map((d) => parseInt(d, 10))
          .filter((d) => !Number.isNaN(d));
        const dayLabels = dayNums.map((d) => DAY_NAMES[d]);
        const last = dayLabels.pop();
        const joined =
          dayLabels.length > 0
            ? `${dayLabels.join(", ")} and ${last}`
            : (last ?? "");
        return `Every ${joined} at ${formatTime(schedule.hour!, schedule.minute!)}`;
      }
      return `Every ${DAY_NAMES[schedule.dayOfWeek!]} at ${formatTime(schedule.hour!, schedule.minute!)}`;
    }

    case "monthly":
      return `Monthly on the ${ordinalSuffix(schedule.dayOfMonth!)} at ${formatTime(schedule.hour!, schedule.minute!)}`;

    case "custom":
      return `Custom: ${schedule.customExpression}`;

    default:
      return expression;
  }
};

export const getNextRuns = (expression: string, count: number = 3): Date[] => {
  const schedule = parseCronExpression(expression);
  const now = new Date();
  const runs: Date[] = [];

  if (schedule.type === "custom") return runs;

  const hour = schedule.hour ?? 9;
  const minute = schedule.minute ?? 0;

  if (schedule.type === "daily") {
    let candidate = new Date(now);
    candidate.setSeconds(0, 0);
    candidate.setHours(hour, minute);
    if (candidate <= now) {
      candidate = new Date(candidate.getTime() + 24 * 60 * 60 * 1000);
    }
    for (let i = 0; i < count; i++) {
      runs.push(new Date(candidate));
      candidate = new Date(candidate.getTime() + 24 * 60 * 60 * 1000);
    }
    return runs;
  }

  if (schedule.type === "weekly") {
    const targetDow = schedule.dayOfWeek ?? 1;
    let candidate = new Date(now);
    candidate.setSeconds(0, 0);
    candidate.setHours(hour, minute);
    while (runs.length < count) {
      if (candidate.getDay() === targetDow && candidate > now) {
        runs.push(new Date(candidate));
      }
      candidate = new Date(candidate.getTime() + 24 * 60 * 60 * 1000);
    }
    return runs;
  }

  if (schedule.type === "monthly") {
    const targetDom = schedule.dayOfMonth ?? 1;
    let year = now.getFullYear();
    let month = now.getMonth();

    while (runs.length < count) {
      const candidate = new Date(year, month, targetDom, hour, minute, 0, 0);
      if (candidate > now) {
        runs.push(candidate);
      }
      month += 1;
      if (month > 11) {
        month = 0;
        year += 1;
      }
    }
    return runs;
  }

  return runs;
};
