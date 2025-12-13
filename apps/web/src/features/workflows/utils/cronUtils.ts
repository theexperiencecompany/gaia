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

export interface SchedulePreset {
  id: string;
  label: string;
  description: string;
  cron: string;
  schedule: CronSchedule;
}

export const schedulePresets: SchedulePreset[] = [
  {
    id: "daily_9am",
    label: "Daily at 9:00 AM",
    description: "Every day at 9:00 AM",
    cron: "0 9 * * *",
    schedule: { type: "daily", hour: 9, minute: 0 },
  },
  {
    id: "weekly_monday_9am",
    label: "Weekly on Monday at 9:00 AM",
    description: "Every Monday at 9:00 AM",
    cron: "0 9 * * 1",
    schedule: { type: "weekly", hour: 9, minute: 0, dayOfWeek: 1 },
  },
  {
    id: "monthly_1st_9am",
    label: "Monthly on 1st at 9:00 AM",
    description: "1st day of every month at 9:00 AM",
    cron: "0 9 1 * *",
    schedule: { type: "monthly", hour: 9, minute: 0, dayOfMonth: 1 },
  },
  {
    id: "weekdays_9am",
    label: "Weekdays at 9:00 AM",
    description: "Monday through Friday at 9:00 AM",
    cron: "0 9 * * 1-5",
    schedule: { type: "custom", customExpression: "0 9 * * 1-5" },
  },
  {
    id: "twice_daily",
    label: "Twice Daily (9 AM & 6 PM)",
    description: "Every day at 9:00 AM and 6:00 PM",
    cron: "0 9,18 * * *",
    schedule: { type: "custom", customExpression: "0 9,18 * * *" },
  },
];

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

  // Daily: 0 9 * * *
  if (dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
    return {
      type: "daily",
      minute: parseInt(minute),
      hour: parseInt(hour),
    };
  }

  // Weekly: 0 9 * * 1
  if (dayOfMonth === "*" && month === "*" && dayOfWeek !== "*") {
    return {
      type: "weekly",
      minute: parseInt(minute),
      hour: parseInt(hour),
      dayOfWeek: parseInt(dayOfWeek),
    };
  }

  // Monthly: 0 9 1 * *
  if (dayOfMonth !== "*" && month === "*" && dayOfWeek === "*") {
    return {
      type: "monthly",
      minute: parseInt(minute),
      hour: parseInt(hour),
      dayOfMonth: parseInt(dayOfMonth),
    };
  }

  // Yearly: 0 9 1 1 *
  if (dayOfMonth !== "*" && month !== "*" && dayOfWeek === "*") {
    return {
      type: "yearly",
      minute: parseInt(minute),
      hour: parseInt(hour),
      dayOfMonth: parseInt(dayOfMonth),
      month: parseInt(month),
    };
  }

  // Everything else is custom
  return { type: "custom", customExpression: cron };
};

export const getScheduleDescription = (cron: string): string => {
  const schedule = parseCronExpression(cron);

  const formatTime = (hour: number, minute: number) => {
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
      // Try to match common patterns
      if (schedule.customExpression === "0 9,18 * * *") {
        return "Twice daily at 9:00 AM and 6:00 PM";
      }
      if (schedule.customExpression === "0 9 * * 1-5") {
        return "Weekdays at 9:00 AM";
      }
      return `Custom: ${schedule.customExpression}`;

    default:
      return cron;
  }
};
