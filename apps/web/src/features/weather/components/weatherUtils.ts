const weekdayFormatter = new Intl.DateTimeFormat("en-US", {
  weekday: "long",
});

export function formatTime(timestamp: number, timezone: number): string {
  const date = new Date((timestamp + timezone) * 1000);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function celsiusToFahrenheit(celsius: number): number {
  return (celsius * 9) / 5 + 32;
}

export function getDayOfWeek(dateStr: string): string {
  const date = new Date(dateStr);
  return weekdayFormatter.format(date);
}
