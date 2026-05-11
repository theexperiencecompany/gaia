// Get start and end of a month for a given date
export const getMonthRange = (date: Date): { start: Date; end: Date } => {
  const start = new Date(date.getFullYear(), date.getMonth(), 1);
  const end = new Date(date.getFullYear(), date.getMonth() + 1, 0, 23, 59, 59);
  return { start, end };
};

// Get the previous month's range
export const getPreviousMonthRange = (
  date: Date,
): { start: Date; end: Date } => {
  const prevMonth = new Date(date.getFullYear(), date.getMonth() - 1, 1);
  return getMonthRange(prevMonth);
};

// Get the next month's range
export const getNextMonthRange = (date: Date): { start: Date; end: Date } => {
  const nextMonth = new Date(date.getFullYear(), date.getMonth() + 1, 1);
  return getMonthRange(nextMonth);
};

// Generate all dates for a given month
export const generateMonthDates = (date: Date): Date[] => {
  const { start, end } = getMonthRange(date);
  const dates: Date[] = [];
  const current = new Date(start);

  while (current <= end) {
    dates.push(new Date(current));
    current.setDate(current.getDate() + 1);
  }

  return dates;
};

// Get initial date range: current month ± 1 month
export const getInitialMonthlyDateRange = (currentDate: Date): Date[] => {
  const prevMonth = new Date(
    currentDate.getFullYear(),
    currentDate.getMonth() - 1,
    1,
  );
  const nextMonth = new Date(
    currentDate.getFullYear(),
    currentDate.getMonth() + 1,
    1,
  );

  const dates: Date[] = [];

  // Add previous month
  dates.push(...generateMonthDates(prevMonth));

  // Add current month
  dates.push(...generateMonthDates(currentDate));

  // Add next month
  dates.push(...generateMonthDates(nextMonth));

  return dates;
};

export const getInitialDateRange = (
  currentWeek: Date,
  weeksBuffer = 2,
): Date[] => {
  const startOfWeek = new Date(currentWeek);
  const day = startOfWeek.getDay();
  const daysFromMonday = day === 0 ? 6 : day - 1;
  startOfWeek.setDate(startOfWeek.getDate() - daysFromMonday - weeksBuffer * 7);

  const totalDays = (weeksBuffer * 2 + 1) * 7;
  return Array.from({ length: totalDays }, (_, i) => {
    const date = new Date(startOfWeek);
    date.setDate(startOfWeek.getDate() + i);
    return date;
  });
};

export const getExtendedDates = (
  currentWeek: Date,
  weeksBuffer = 2,
): Date[] => {
  const startOfWeek = new Date(currentWeek);
  const day = startOfWeek.getDay();
  const daysFromMonday = day === 0 ? 6 : day - 1;
  startOfWeek.setDate(startOfWeek.getDate() - daysFromMonday - weeksBuffer * 7);

  const totalDays = (weeksBuffer * 2 + 1) * 7;
  return Array.from({ length: totalDays }, (_, i) => {
    const date = new Date(startOfWeek);
    date.setDate(startOfWeek.getDate() + i);
    return date;
  });
};

// Generate dates extending forward from a start date
export const generateDatesForward = (
  startDate: Date,
  count: number,
): Date[] => {
  return Array.from({ length: count }, (_, i) => {
    const date = new Date(startDate);
    date.setDate(startDate.getDate() + i);
    return date;
  });
};

// Generate dates extending backward from an end date
export const generateDatesBackward = (endDate: Date, count: number): Date[] => {
  return Array.from({ length: count }, (_, i) => {
    const date = new Date(endDate);
    date.setDate(endDate.getDate() - (count - 1 - i));
    return date;
  });
};

// Merge new dates into existing array, avoiding duplicates
export const mergeDateRanges = (
  existing: Date[],
  newDates: Date[],
  position: "start" | "end",
): Date[] => {
  if (existing.length === 0) return newDates;

  const existingDateStrings = new Set(
    existing.map((d) => d.toISOString().split("T")[0]),
  );

  const uniqueNewDates = newDates.filter(
    (d) => !existingDateStrings.has(d.toISOString().split("T")[0]),
  );

  if (position === "start") {
    return [...uniqueNewDates, ...existing];
  }
  return [...existing, ...uniqueNewDates];
};
