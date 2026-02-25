const today = new Date();

function dayOffset(offset: number): string {
  const d = new Date(today);
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}

export const DEMO_CALENDARS = [
  { id: "primary", summary: "Primary", backgroundColor: "#00bbff" },
  { id: "work", summary: "Work", backgroundColor: "#7c3aed" },
  { id: "personal", summary: "Personal", backgroundColor: "#10b981" },
  { id: "fitness", summary: "Fitness", backgroundColor: "#f59e0b" },
  { id: "side-project", summary: "Side Project", backgroundColor: "#ec4899" },
];

export const DEMO_EVENTS = [
  // Day -1 (yesterday)
  {
    id: "ce1",
    summary: "Marketing Sync",
    start: { dateTime: `${dayOffset(-1)}T11:00:00` },
    end: { dateTime: `${dayOffset(-1)}T11:30:00` },
    calendarId: "primary",
  },
  {
    id: "ce2",
    summary: "API Review",
    start: { dateTime: `${dayOffset(-1)}T14:00:00` },
    end: { dateTime: `${dayOffset(-1)}T15:00:00` },
    calendarId: "work",
  },
  {
    id: "ce3",
    summary: "Evening Run",
    start: { dateTime: `${dayOffset(-1)}T18:00:00` },
    end: { dateTime: `${dayOffset(-1)}T19:00:00` },
    calendarId: "fitness",
  },

  // Day 0 (today)
  {
    id: "ce4",
    summary: "Standup — Engineering",
    start: { dateTime: `${dayOffset(0)}T09:30:00` },
    end: { dateTime: `${dayOffset(0)}T09:45:00` },
    calendarId: "primary",
  },
  {
    id: "ce5",
    summary: "1:1 with Sarah",
    start: { dateTime: `${dayOffset(0)}T11:00:00` },
    end: { dateTime: `${dayOffset(0)}T11:30:00` },
    calendarId: "primary",
  },
  {
    id: "ce6",
    summary: "Lunch with Alex",
    start: { dateTime: `${dayOffset(0)}T12:30:00` },
    end: { dateTime: `${dayOffset(0)}T13:30:00` },
    calendarId: "personal",
  },
  {
    id: "ce7",
    summary: "Investor Call — Sequoia",
    start: { dateTime: `${dayOffset(0)}T14:00:00` },
    end: { dateTime: `${dayOffset(0)}T15:00:00` },
    calendarId: "work",
  },
  {
    id: "ce8",
    summary: "Product Review",
    start: { dateTime: `${dayOffset(0)}T16:00:00` },
    end: { dateTime: `${dayOffset(0)}T17:00:00` },
    calendarId: "primary",
  },
  {
    id: "ce9",
    summary: "Gym",
    start: { dateTime: `${dayOffset(0)}T18:00:00` },
    end: { dateTime: `${dayOffset(0)}T19:00:00` },
    calendarId: "fitness",
  },

  // Day +1
  {
    id: "ce10",
    summary: "Design Sprint",
    start: { dateTime: `${dayOffset(1)}T10:00:00` },
    end: { dateTime: `${dayOffset(1)}T12:00:00` },
    calendarId: "primary",
  },
  {
    id: "ce11",
    summary: "Team Retro",
    start: { dateTime: `${dayOffset(1)}T14:00:00` },
    end: { dateTime: `${dayOffset(1)}T15:00:00` },
    calendarId: "work",
  },
  {
    id: "ce12",
    summary: "Side Project Coding",
    start: { dateTime: `${dayOffset(1)}T16:00:00` },
    end: { dateTime: `${dayOffset(1)}T18:00:00` },
    calendarId: "side-project",
  },
  {
    id: "ce13",
    summary: "Yoga Class",
    start: { dateTime: `${dayOffset(1)}T18:00:00` },
    end: { dateTime: `${dayOffset(1)}T19:00:00` },
    calendarId: "fitness",
  },

  // Day +2
  {
    id: "ce14",
    summary: "HIIT Class",
    start: { dateTime: `${dayOffset(2)}T07:00:00` },
    end: { dateTime: `${dayOffset(2)}T07:45:00` },
    calendarId: "fitness",
  },
  {
    id: "ce15",
    summary: "Board Meeting Prep",
    start: { dateTime: `${dayOffset(2)}T09:00:00` },
    end: { dateTime: `${dayOffset(2)}T10:30:00` },
    calendarId: "work",
  },
  {
    id: "ce16",
    summary: "UI Polish Sprint",
    start: { dateTime: `${dayOffset(2)}T13:00:00` },
    end: { dateTime: `${dayOffset(2)}T14:30:00` },
    calendarId: "side-project",
  },
  {
    id: "ce17",
    summary: "Coffee with David",
    start: { dateTime: `${dayOffset(2)}T15:00:00` },
    end: { dateTime: `${dayOffset(2)}T15:30:00` },
    calendarId: "personal",
  },

  // Day +3
  {
    id: "ce18",
    summary: "Sprint Planning",
    start: { dateTime: `${dayOffset(3)}T10:00:00` },
    end: { dateTime: `${dayOffset(3)}T11:00:00` },
    calendarId: "primary",
  },
  {
    id: "ce19",
    summary: "Customer Demo",
    start: { dateTime: `${dayOffset(3)}T13:00:00` },
    end: { dateTime: `${dayOffset(3)}T14:00:00` },
    calendarId: "work",
  },
  {
    id: "ce20",
    summary: "Dentist",
    start: { dateTime: `${dayOffset(3)}T16:00:00` },
    end: { dateTime: `${dayOffset(3)}T16:30:00` },
    calendarId: "personal",
  },
  {
    id: "ce21",
    summary: "Swimming",
    start: { dateTime: `${dayOffset(3)}T17:30:00` },
    end: { dateTime: `${dayOffset(3)}T18:30:00` },
    calendarId: "fitness",
  },

  // Day +4
  {
    id: "ce22",
    summary: "Morning Run",
    start: { dateTime: `${dayOffset(4)}T06:30:00` },
    end: { dateTime: `${dayOffset(4)}T07:15:00` },
    calendarId: "fitness",
  },
  {
    id: "ce23",
    summary: "All Hands",
    start: { dateTime: `${dayOffset(4)}T10:00:00` },
    end: { dateTime: `${dayOffset(4)}T11:00:00` },
    calendarId: "primary",
  },
  {
    id: "ce24",
    summary: "Hiring Panel",
    start: { dateTime: `${dayOffset(4)}T14:00:00` },
    end: { dateTime: `${dayOffset(4)}T15:30:00` },
    calendarId: "work",
  },
  {
    id: "ce25",
    summary: "Dinner with Friends",
    start: { dateTime: `${dayOffset(4)}T19:00:00` },
    end: { dateTime: `${dayOffset(4)}T21:00:00` },
    calendarId: "personal",
  },

  // Day +5
  {
    id: "ce26",
    summary: "Side Project Planning",
    start: { dateTime: `${dayOffset(5)}T09:00:00` },
    end: { dateTime: `${dayOffset(5)}T10:00:00` },
    calendarId: "side-project",
  },
  {
    id: "ce27",
    summary: "Architecture Review",
    start: { dateTime: `${dayOffset(5)}T11:00:00` },
    end: { dateTime: `${dayOffset(5)}T12:00:00` },
    calendarId: "primary",
  },
  {
    id: "ce28",
    summary: "1:1 with Manager",
    start: { dateTime: `${dayOffset(5)}T15:00:00` },
    end: { dateTime: `${dayOffset(5)}T16:00:00` },
    calendarId: "work",
  },
  {
    id: "ce29",
    summary: "Basketball",
    start: { dateTime: `${dayOffset(5)}T17:00:00` },
    end: { dateTime: `${dayOffset(5)}T18:00:00` },
    calendarId: "fitness",
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
