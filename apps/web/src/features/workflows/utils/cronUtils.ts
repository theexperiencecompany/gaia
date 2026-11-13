// Comprehensive cron expression builder and parser

export interface CronSchedule {
  type: "daily" | "weekly" | "monthly" | "yearly" | "custom";
  minute?: number;
  hour?: number;
  dayOfWeek?: number; // 0-6 (Sunday-Saturday)
  dayOfMonth?: number; // 1-31
  month?: number; // 1-12
  customExpression?: string;
}

export const buildCronExpression = (schedule: CronSchedule): string => {
  const { type, minute = 0, hour = 9, dayOfWeek, dayOfMonth, month } = schedule;

  switch (type) {
    case "daily":
      return `${minute} ${hour} * * *`;

    case "weekly":
      return `${minute} ${hour} * * ${dayOfWeek ?? 1}`;

    case "monthly":
      return `${minute} ${hour} ${dayOfMonth ?? 1} * *`;

    case "yearly":
      return `${minute} ${hour} ${dayOfMonth ?? 1} ${month ?? 1} *`;

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

  // Only treat as a simple named schedule if minute and hour are plain integers.
  // Step/range expressions like */22, */2, 0,30, 1-5 fall through to custom.
  const isSimpleInt = (s: string) => /^\d+$/.test(s);

  // Daily: 0 9 * * *
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

  // Weekly: 0 9 * * 1
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

  // Monthly: 0 9 1 * *
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

  // Yearly: 0 9 1 1 *
  if (
    isSimpleInt(minute) &&
    isSimpleInt(hour) &&
    isSimpleInt(dayOfMonth) &&
    isSimpleInt(month) &&
    dayOfWeek === "*"
  ) {
    return {
      type: "yearly",
      minute: parseInt(minute, 10),
      hour: parseInt(hour, 10),
      dayOfMonth: parseInt(dayOfMonth, 10),
      month: parseInt(month, 10),
    };
  }

  // Everything else (step expressions, ranges, lists) is custom
  return { type: "custom", customExpression: cron };
};

export const getScheduleDescription = (cron: string): string => {
  const schedule = parseCronExpression(cron);

  const formatTime = (hour: number, minute: number): string => {
    const ampm = hour >= 12 ? "PM" : "AM";
    const displayHour = hour > 12 ? hour - 12 : hour === 0 ? 12 : hour;
    const displayMinute = minute.toString().padStart(2, "0");
    return `${displayHour}:${displayMinute} ${ampm}`;
  };

  const dayNames = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
  ];
  const monthNames = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];

  switch (schedule.type) {
    case "daily":
      return `Daily at ${formatTime(schedule.hour!, schedule.minute!)}`;

    case "weekly":
      return `Every ${dayNames[schedule.dayOfWeek!]} at ${formatTime(schedule.hour!, schedule.minute!)}`;

    case "monthly": {
      const ordinal =
        schedule.dayOfMonth === 1
          ? "1st"
          : schedule.dayOfMonth === 2
            ? "2nd"
            : schedule.dayOfMonth === 3
              ? "3rd"
              : `${schedule.dayOfMonth}th`;
      return `Monthly on the ${ordinal} at ${formatTime(schedule.hour!, schedule.minute!)}`;
    }

    case "yearly":
      return `Yearly on ${monthNames[schedule.month! - 1]} ${schedule.dayOfMonth} at ${formatTime(schedule.hour!, schedule.minute!)}`;

    case "custom":
      return `Custom: ${schedule.customExpression}`;

    default:
      return cron;
  }
};
