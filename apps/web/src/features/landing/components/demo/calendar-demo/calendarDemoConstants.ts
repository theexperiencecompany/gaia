const today = new Date();
const todayStr = today.toISOString().slice(0, 10);

function dayOffset(offset: number): string {
  const d = new Date(today);
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}

export const DEMO_CALENDARS = [
  { id: "primary", summary: "Primary", backgroundColor: "#00bbff" },
  { id: "work", summary: "Work", backgroundColor: "#7c3aed" },
  { id: "personal", summary: "Personal", backgroundColor: "#10b981" },
];

export const DEMO_EVENTS = [
  {
    id: "ce1",
    summary: "Standup — Engineering",
    start: { dateTime: `${todayStr}T09:30:00` },
    end: { dateTime: `${todayStr}T09:45:00` },
    calendarId: "primary",
  },
  {
    id: "ce2",
    summary: "1:1 with Sarah",
    start: { dateTime: `${todayStr}T11:00:00` },
    end: { dateTime: `${todayStr}T11:30:00` },
    calendarId: "primary",
  },
  {
    id: "ce3",
    summary: "Investor Call — Sequoia",
    start: { dateTime: `${todayStr}T14:00:00` },
    end: { dateTime: `${todayStr}T15:00:00` },
    calendarId: "work",
  },
  {
    id: "ce4",
    summary: "Lunch with Alex",
    start: { dateTime: `${todayStr}T12:30:00` },
    end: { dateTime: `${todayStr}T13:30:00` },
    calendarId: "personal",
  },
  {
    id: "ce5",
    summary: "Product Review",
    start: { dateTime: `${todayStr}T16:00:00` },
    end: { dateTime: `${todayStr}T17:00:00` },
    calendarId: "primary",
  },
  {
    id: "ce6",
    summary: "Design Sprint",
    start: { dateTime: `${dayOffset(1)}T10:00:00` },
    end: { dateTime: `${dayOffset(1)}T12:00:00` },
    calendarId: "primary",
  },
  {
    id: "ce7",
    summary: "Team Retro",
    start: { dateTime: `${dayOffset(1)}T14:00:00` },
    end: { dateTime: `${dayOffset(1)}T15:00:00` },
    calendarId: "work",
  },
  {
    id: "ce8",
    summary: "Yoga Class",
    start: { dateTime: `${dayOffset(1)}T18:00:00` },
    end: { dateTime: `${dayOffset(1)}T19:00:00` },
    calendarId: "personal",
  },
  {
    id: "ce9",
    summary: "Board Meeting Prep",
    start: { dateTime: `${dayOffset(2)}T09:00:00` },
    end: { dateTime: `${dayOffset(2)}T10:30:00` },
    calendarId: "work",
  },
  {
    id: "ce10",
    summary: "Coffee with David",
    start: { dateTime: `${dayOffset(2)}T15:00:00` },
    end: { dateTime: `${dayOffset(2)}T15:30:00` },
    calendarId: "personal",
  },
  {
    id: "ce11",
    summary: "Sprint Planning",
    start: { dateTime: `${dayOffset(3)}T10:00:00` },
    end: { dateTime: `${dayOffset(3)}T11:00:00` },
    calendarId: "primary",
  },
  {
    id: "ce12",
    summary: "Marketing Sync",
    start: { dateTime: `${dayOffset(-1)}T11:00:00` },
    end: { dateTime: `${dayOffset(-1)}T11:30:00` },
    calendarId: "primary",
  },
  {
    id: "ce13",
    summary: "API Review",
    start: { dateTime: `${dayOffset(-1)}T14:00:00` },
    end: { dateTime: `${dayOffset(-1)}T15:00:00` },
    calendarId: "work",
  },
];

// Generate 7 days centered on today
export function getDemoWeekDates(): Date[] {
  const dates: Date[] = [];
  for (let i = -1; i <= 5; i++) {
    const d = new Date(today);
    d.setDate(d.getDate() + i);
    dates.push(d);
  }
  return dates;
}

export const HOURS = Array.from({ length: 24 }, (_, i) => i);

export const PX_PER_HOUR = 64;
export const PX_PER_MINUTE = PX_PER_HOUR / 60;
export const DAY_START_HOUR = 0;
