import type { AlternativeData } from "../alternativesData";

export const entry: AlternativeData = {
  slug: "linear",
  name: "Linear",
  domain: "linear.app",
  category: "task-manager",
  tagline:
    "Engineering issue tracking built for teams — not personal productivity",
  painPoints: [
    "Linear's cycles, projects, and triage workflows are designed for engineering sprints — solo users and non-eng teams get complexity they don't need",
    "No email integration: action items from Gmail threads require manual copy into Linear issues",
    "No calendar awareness — Linear doesn't know if you're in meetings all day and can't adjust workload suggestions accordingly",
    "Pricing is per-seat, making it expensive for small teams or individuals who just want clean task management",
    "No AI that proactively surfaces what to work on — Linear shows your backlog, but you decide priorities manually",
  ],
  metaTitle:
    "Linear Alternative | GAIA — AI Task Manager for Individuals & Small Teams",
  metaDescription:
    "Want Linear's clean UX without the engineering-team overhead? GAIA is an open-source AI productivity assistant that manages tasks, email, and calendar in one place. Free tier available. Self-hostable.",
  keywords: [
    "linear alternative",
    "linear alternative free",
    "linear alternative open source",
    "linear alternative self hosted",
    "linear alternative reddit",
    "linear app alternative",
    "linear alternative 2026",
  ],
  whyPeopleLook:
    "Linear is widely praised for its speed and design, but its DNA is engineering issue tracking — cycles, sprints, and triage are team constructs that feel like overhead for solo developers or non-engineering users. People searching for a Linear alternative often want the clean interface and keyboard-first UX without the team-oriented structure, or they need a tool that also handles email and calendar alongside tasks.",
  gaiaFitScore: 3,
  gaiaReplaces: [
    "Personal task lists and backlogs in Linear",
    "Manual creation of issues from email action items",
    "Separate reminders for Linear tasks due today",
    "Switching between Linear and a calendar app to plan your day",
  ],
  gaiaAdvantages: [
    "GAIA handles personal tasks, email, and calendar together — Linear handles only engineering issues",
    "Tasks created automatically from emails and meeting action items without manual entry",
    "Proactive workload awareness — GAIA knows your calendar is full and adjusts task surfacing",
    "Open source and self-hostable; Linear is closed-source SaaS",
    "Flat $20/month Pro pricing vs Linear's per-seat model",
  ],
  migrationSteps: [
    "Export your current Linear issues as CSV and import task titles and descriptions into GAIA",
    "Connect Gmail so GAIA can auto-create tasks from emails that previously became Linear issues manually",
    "Link Google Calendar so GAIA can surface today's tasks against your available time blocks",
    "Use GAIA's daily briefing to replace the Linear inbox triage routine",
  ],
  faqs: [
    {
      question: "Is GAIA a project management tool like Linear?",
      answer:
        "GAIA is a personal AI productivity assistant — it handles tasks, email, calendar, and automations for individuals and small teams. It lacks Linear's engineering-specific features like cycles, sprints, and GitHub issue sync, but covers personal productivity breadth that Linear doesn't touch.",
    },
    {
      question: "Can GAIA integrate with Linear?",
      answer:
        "GAIA supports 50+ integrations via MCP. While direct Linear sync depends on available MCP connectors, GAIA can capture action items from email and meetings and manage them independently, reducing your reliance on Linear for personal task tracking.",
    },
    {
      question: "Is there a free Linear alternative?",
      answer:
        "GAIA has a free tier and is open source — you can self-host it at no cost via Docker. Linear's free plan is limited to small teams and lacks advanced features.",
    },
    {
      question: "Why do solo developers leave Linear?",
      answer:
        "Solo developers often find Linear's team constructs (cycles, triage, projects) add process overhead without benefit. They want fast task capture, keyboard shortcuts, and a clean UI — but also email and calendar integration that Linear doesn't provide.",
    },
  ],
};
