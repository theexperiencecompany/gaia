import type { AlternativeData } from "../alternativesData";

export const entry: AlternativeData = {
  slug: "copilot",
  name: "Microsoft Copilot",
  domain: "copilot.microsoft.com",
  category: "ai-assistant",
  tagline: "Microsoft's AI assistant integrated across the Microsoft 365 suite",
  painPoints: [
    "Requires Microsoft 365 subscription; locked into the Microsoft ecosystem",
    "High enterprise pricing puts Copilot out of reach for individuals",
    "Limited outside of Office apps — cannot manage non-Microsoft tools",
    "Privacy concerns around Microsoft processing enterprise data",
    "Less effective for users not deeply embedded in the Microsoft stack",
  ],
  metaTitle: "Best Microsoft Copilot Alternative in 2026 | GAIA",
  metaDescription:
    "Not on Microsoft 365? GAIA is a proactive AI assistant that works with Gmail, Google Calendar, and 50+ tools — no Microsoft subscription required. Free tier available.",
  keywords: [
    "microsoft copilot alternative",
    "copilot alternative",
    "best copilot alternative",
    "ai assistant without microsoft",
    "copilot vs gaia",
    "google workspace ai assistant",
    "free microsoft copilot alternative",
    "open source microsoft copilot alternative",
    "self-hosted microsoft copilot alternative",
    "microsoft copilot alternative for individuals",
    "microsoft copilot alternative 2026",
    "proactive AI assistant",
    "AI that reads email",
    "self-hosted AI assistant",
  ],
  whyPeopleLook:
    "Microsoft Copilot is powerful within the Microsoft 365 ecosystem, but it is inaccessible to anyone not using Outlook, Teams, and Word as their primary tools. The enterprise licensing starts at $30/user/month on top of existing Microsoft 365 costs, making it unaffordable for individuals and small businesses. Users on Google Workspace, or those using a mix of tools from different vendors, find that Copilot simply cannot help them. GAIA is the ecosystem-agnostic alternative: it works with Gmail, Google Calendar, Todoist, Slack, Discord, and 50+ tools via MCP, without requiring any Microsoft subscription.",
  gaiaFitScore: 4,
  gaiaReplaces: [
    "Email triage and drafting for Gmail users",
    "Calendar management and scheduling outside of Outlook",
    "Task management for non-Teams users via Todoist integration",
    "Meeting summarization without Microsoft Teams",
    "Workflow automation across non-Microsoft SaaS tools",
  ],
  gaiaAdvantages: [
    "Works with Google Workspace, not just Microsoft 365",
    "No enterprise licensing required — free tier available",
    "Open-source codebase means no vendor lock-in",
    "Self-hostable for organizations with strict data compliance needs",
    "50+ tool integrations beyond the Microsoft ecosystem",
  ],
  migrationSteps: [
    "Connect GAIA to your Gmail account via OAuth",
    "Link Google Calendar for meeting and scheduling intelligence",
    "Add your preferred task manager (Todoist, GAIA tasks)",
    "Invite GAIA to your Slack or Discord workspace for team-accessible AI",
  ],
  faqs: [
    {
      question:
        "Does GAIA work with Google Workspace instead of Microsoft 365?",
      answer:
        "Yes. GAIA is designed primarily for Gmail and Google Calendar users. It does not require any Microsoft subscription.",
    },
    {
      question: "Is GAIA cheaper than Microsoft Copilot?",
      answer:
        "Significantly so. Microsoft 365 Copilot starts at $30/user/month on top of your existing Microsoft 365 plan. GAIA Pro is $20/month for an individual, with a free tier and self-hosting option.",
    },
    {
      question: "Can GAIA integrate with Microsoft tools if I use both?",
      answer:
        "GAIA can connect to some Microsoft services via MCP integrations. For organizations using both Google Workspace and Microsoft tools, GAIA can serve as a bridge for personal productivity tasks.",
    },
    {
      question: "Is GAIA open-source unlike Microsoft Copilot?",
      answer:
        "Yes. GAIA is fully open-source on GitHub. You can inspect the code, contribute, and self-host with your own infrastructure and API keys.",
    },
  ],
};
