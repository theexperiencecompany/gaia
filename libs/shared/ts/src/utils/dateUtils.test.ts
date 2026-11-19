import { describe, expect, it } from "vitest";

import {
  dayName,
  formatClockTime,
  formatDate,
  formatDateUTC,
  formatDay,
  formatHour,
  formatInboxTime,
  formatMessageTime,
  formatRelativeDate,
  formatTime,
  formatTimeRange,
  parseCronToHuman,
} from "./dateUtils";

const NOW = new Date(2026, 10, 16, 15, 45);
const minutesAgo = (minutes: number) =>
  new Date(NOW.getTime() - minutes * 60_000);

describe("dates and times written for a reader", () => {
  it("names today, yesterday and tomorrow, and nothing else", () => {
    expect(dayName(new Date(2026, 10, 16, 1), NOW)).toBe("Today");
    expect(dayName(new Date(2026, 10, 15, 23), NOW)).toBe("Yesterday");
    expect(dayName(new Date(2026, 10, 17, 0), NOW)).toBe("Tomorrow");
    expect(dayName(new Date(2026, 10, 14), NOW)).toBeNull();
  });

  it("writes an hour as the locale does", () => {
    expect(formatHour(22, "en-US")).toBe("10 PM");
    expect(formatHour(32, "en-US")).toBe("8 AM");
    expect(formatHour(22, "en-GB")).toBe("22");
  });

  it("writes a time of day and a wall-clock HH:MM", () => {
    expect(formatTime(NOW, { locale: "en-US" })).toBe("3:45 PM");
    expect(formatClockTime("13:05", "en-US")).toBe("1:05 PM");
    expect(formatClockTime("13:05", "en-GB")).toBe("13:05");
  });

  it("shares what both ends of a time range share", () => {
    const range = formatTimeRange(
      new Date(2026, 10, 16, 10),
      new Date(2026, 10, 16, 11, 30),
      "en-US",
    );
    // ICU pads the dash with thin spaces.
    expect(range.replace(/\s/g, " ")).toBe("10:00 – 11:30 AM");
  });

  it("writes a date in each named shape", () => {
    const day = new Date(2026, 10, 16, 9);
    expect(formatDate(day, "short", { locale: "en-US" })).toBe("Nov 16");
    expect(formatDate(day, "medium", { locale: "en-US" })).toBe("Nov 16, 2026");
    expect(formatDate(day, "long", { locale: "en-US" })).toBe(
      "November 16, 2026",
    );
    expect(formatDate(day, "day", { locale: "en-US" })).toBe("Mon, Nov 16");
    expect(formatDate(day, "day", { locale: "en-GB" })).toBe("Mon 16 Nov");
    expect(formatDate(day, "dayTime", { locale: "en-US" })).toBe(
      "Mon, Nov 16, 9:00 AM",
    );
  });

  it("names a day when it can, else writes it out", () => {
    expect(formatDay(new Date(), "day", "en-US")).toBe("Today");
    expect(formatDay(new Date(2020, 0, 6), "day", "en-US")).toBe("Mon, Jan 6");
  });

  it("times an inbox row by how long ago it arrived", () => {
    expect(formatInboxTime(minutesAgo(30), NOW, "en-US")).toBe("3:15 PM");
    expect(formatInboxTime(minutesAgo(30 * 60), NOW, "en-US")).toBe(
      "Yesterday",
    );
    expect(formatInboxTime(minutesAgo(72 * 60), NOW, "en-US")).toBe("Nov 13");
  });

  it("says how long ago, then the date", () => {
    const relative = (minutes: number) =>
      formatRelativeDate(minutesAgo(minutes), { now: NOW, locale: "en-US" });
    expect(relative(0)).toBe("Just now");
    expect(relative(5)).toBe("5m ago");
    expect(relative(3 * 60)).toBe("3h ago");
    expect(relative(25 * 60)).toBe("Yesterday");
    expect(relative(3 * 24 * 60)).toBe("3d ago");
    expect(relative(10 * 24 * 60)).toBe("Nov 6");
  });

  it("stamps a chat message with how long ago and its time", () => {
    expect(formatMessageTime(minutesAgo(125), NOW, "en-US")).toBe(
      "2 hours 5 mins ago (1:40 PM)",
    );
    expect(formatMessageTime(minutesAgo(0), NOW, "en-US")).toBe(
      "just now (3:45 PM)",
    );
    expect(formatMessageTime(new Date(2025, 5, 10, 15, 4), NOW, "en-US")).toBe(
      "10th Jun '25 (3:04 PM)",
    );
  });

  it("keeps a UTC calendar day on its day", () => {
    expect(formatDateUTC("2026-07-05")).toBe(
      formatDate(new Date(Date.UTC(2026, 6, 5)), "short", { timeZone: "UTC" }),
    );
  });

  it("writes a cron schedule's time the way a bot message always has", () => {
    expect(parseCronToHuman("0 9 * * *")).toBe("Daily at 9 AM");
    expect(parseCronToHuman("30 9 * * 1")).toBe("Every Monday at 9:30 AM");
  });
});
