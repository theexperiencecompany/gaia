import type { CapabilityGroup } from "./featuresData.types";

export const CAPABILITY_GROUPS: CapabilityGroup[] = [
  {
    heading: "Email and calendar",
    items: [
      {
        text: "Reads, searches, drafts and sends email in Gmail and Outlook, and triages new Gmail on its own",
        href: "/features/email",
      },
      {
        text: "Checks your calendar, finds free slots, creates and moves events, and preps you for meetings",
        href: "/features/calendar",
      },
      {
        text: "Sends a daily briefing of your email, calendar and todos before you ask",
        href: "/features/proactive-ai",
      },
    ],
  },
  {
    heading: "Tasks, goals and reminders",
    items: [
      {
        text: "Manages your to-do list in plain language and turns emails into tasks",
        href: "/features/todos",
      },
      {
        text: "Turns a goal into a step-by-step roadmap",
        href: "/features/goals",
      },
      {
        text: "Sets one-time and recurring reminders",
        href: "/features/reminders",
      },
    ],
  },
  {
    heading: "Workflow automation",
    items: [
      {
        text: "Builds workflows you describe in plain English",
        href: "/features/workflows",
      },
      {
        text: "Runs them on a schedule or when something happens in your tools",
        href: "/features/event-triggers",
      },
      {
        text: "Extends itself with installable skills and generates PDF, DOCX and HTML documents",
        href: "/features/skills",
      },
    ],
  },
  {
    heading: "Memory and intelligence",
    items: [
      {
        text: "Remembers your preferences, people and plans across every conversation",
        href: "/features/memory",
      },
      {
        text: "Researches the web across many sources and summarizes what it found",
        href: "/features/deep-research",
      },
      {
        text: "Generates images and runs code in a secure sandbox",
        href: "/features/code-execution",
      },
    ],
  },
  {
    heading: "Integrations",
    items: [
      {
        text: "Connects Gmail, Google Calendar, Slack, Notion, GitHub, Todoist, Linear and more",
        href: "/features/integrations",
      },
      {
        text: "Works as an MCP client: connect any Model Context Protocol server",
        href: "/features/mcp-support",
      },
      {
        text: "Lets you build, publish and install custom integrations",
        href: "/features/custom-integrations",
      },
    ],
  },
  {
    heading: "Where you use it",
    items: [
      {
        text: "The web app, and a desktop app for macOS, Windows and Linux",
        href: "/download",
      },
      {
        text: "Text it on WhatsApp, Telegram and iMessage, or use it in Slack and Discord",
        href: "/ai-assistant-whatsapp-telegram-imessage",
      },
      {
        text: "On the desktop it reads your screen, uses your clipboard and runs browser tasks in a cloud browser",
        href: "/ai-assistant-that-uses-your-computer",
      },
      {
        text: "Talk to it in real-time voice conversations",
        href: "/features/voice",
      },
    ],
  },
];

export const LIMITS = [
  "It does not make or answer phone calls.",
  "It does not take over your mouse and keyboard to drive other desktop apps.",
];
