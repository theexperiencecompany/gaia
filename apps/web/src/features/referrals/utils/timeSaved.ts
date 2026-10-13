const MINUTES_PER_HOUR = 60;

/** "45 minutes", "1 hour", "6.5 hours": the week's estimate, rounded to the half hour past the first hour. */
export function formatTimeSaved(minutes: number): string {
  if (minutes < MINUTES_PER_HOUR)
    return minutes === 1 ? "1 minute" : `${minutes} minutes`;
  const hours = Math.round((minutes / MINUTES_PER_HOUR) * 2) / 2;
  return hours === 1 ? "1 hour" : `${hours} hours`;
}
