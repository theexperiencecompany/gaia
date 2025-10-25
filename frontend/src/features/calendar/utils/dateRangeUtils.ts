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

export const getDatesAroundSelected = (
  selectedDate: Date,
  daysToShow: number,
  weeksBuffer = 2,
): Date[] => {
  const startOfWeek = new Date(selectedDate);
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

export const getChunkKey = (date: Date): string => {
  const year = date.getFullYear();
  const quarter = Math.floor(date.getMonth() / 3);
  return `${year}-Q${quarter + 1}`;
};

export const getChunkDates = (chunkKey: string): { start: Date; end: Date } => {
  const [year, quarter] = chunkKey.split("-");
  const quarterNum = parseInt(quarter.replace("Q", "")) - 1;

  const start = new Date(parseInt(year), quarterNum * 3, 1);
  const end = new Date(parseInt(year), (quarterNum + 1) * 3, 0, 23, 59, 59);

  return { start, end };
};

export const getRequiredChunks = (dates: Date[]): string[] => {
  const chunks = new Set<string>();
  dates.forEach((date) => {
    chunks.add(getChunkKey(date));
  });
  return Array.from(chunks);
};
