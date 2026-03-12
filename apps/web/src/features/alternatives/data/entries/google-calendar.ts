import type { AlternativeData } from "../alternativesData";

export const entry: AlternativeData = {
  slug: "google-calendar",
  name: "Google Calendar",
  domain: "calendar.google.com",
  category: "calendar",
  tagline:
    "The world's most-used calendar — but it only stores events, not intelligence",
  painPoints: [
    "Events sit in Calendar with no briefing, context, or preparation reminders — you have to remember to check yourself",
    "Scheduling conflicts require manual detection; Calendar won't warn you that a meeting overlaps a deep-work block you set last month",
    "No automatic event creation from email — you must manually copy flight confirmations, dinner reservations, and meeting invites",
    "Natural language entry is limited; creating a recurring event with exceptions requires navigating multiple menus",
    "No cross-tool awareness — Calendar doesn't know about your Todoist tasks, Gmail threads, or Notion docs related to a meeting",
  ],
  metaTitle: "Google Calendar Alternative | GAIA — AI-Powered Smart Calendar",
  metaDescription:
    "Looking for a smarter Google Calendar alternative? GAIA adds an AI intelligence layer to your calendar: proactive briefings, automatic event creation from email, conflict detection, and 50+ integrations. Open source, self-hostable.",
  keywords: [
    "google calendar alternative",
    "google calendar alternative free",
    "google calendar alternative open source",
    "google calendar app alternative",
    "better google calendar app",
    "ai google calendar alternative",
    "smart calendar app",
    "google calendar alternative 2026",
  ],
  whyPeopleLook:
    "Google Calendar is a passive event store — it holds your schedule but offers no intelligence about it. Users grow frustrated when they miss preparation steps for meetings, fail to catch scheduling conflicts until the last minute, or spend time manually entering events that were already described in emails. The search for an alternative is really a search for a calendar that thinks ahead.",
  gaiaFitScore: 3,
  gaiaReplaces: [
    "Manual meeting briefing lookups before calls",
    "Copy-pasting event details from emails into Calendar",
    "Manually scanning the week for conflicts or overloaded days",
    "Separate reminder apps for pre-meeting prep",
  ],
  gaiaAdvantages: [
    "Proactive daily briefings pulled from calendar events without you asking",
    "Automatic event creation from Gmail confirmations and meeting invites",
    "Conflict detection across calendar + task load, not just event overlaps",
    "GAIA connects calendar context to email threads, tasks, and notes in one place",
    "Open source and self-hostable; Google Calendar is a closed cloud service",
  ],
  migrationSteps: [
    "Connect your Google Calendar to GAIA via the Google integration (GAIA reads and writes events)",
    "Enable Gmail integration so GAIA can detect event-worthy emails and create calendar entries automatically",
    "Set up your daily briefing preference so GAIA surfaces your schedule and meeting context each morning",
    "Ask GAIA to audit next week's calendar for conflicts, overloaded days, and missing prep tasks",
  ],
  faqs: [
    {
      question: "Does GAIA replace Google Calendar entirely?",
      answer:
        "No — and that's intentional. Google Calendar remains your source of truth for events. GAIA is the intelligence layer on top: it reads your calendar, creates events from emails, surfaces briefings proactively, and connects your schedule to tasks and email context. A fit score of 3/5 reflects this complementary relationship.",
    },
    {
      question: "Can GAIA create Google Calendar events from emails?",
      answer:
        "Yes. GAIA's Gmail integration detects flight confirmations, dinner reservations, meeting invites, and other event-worthy emails, then creates or suggests Google Calendar events automatically — a capability Google Calendar itself lacks natively.",
    },
    {
      question: "Is GAIA free compared to Google Calendar?",
      answer:
        "Google Calendar is free. GAIA has a free tier and a Pro plan at $20/month flat (no per-seat fees). For self-hosters, GAIA is entirely free to run on your own infrastructure via Docker.",
    },
    {
      question: "What does GAIA add to Google Calendar that Google doesn't?",
      answer:
        "Proactive meeting briefings, automatic event creation from email, cross-tool conflict awareness (tasks + calendar together), natural language scheduling via chat, and a memory layer that ties past meeting notes to future events — none of which Google Calendar provides natively.",
    },
  ],
};
