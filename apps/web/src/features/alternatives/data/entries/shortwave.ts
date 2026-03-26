import type { AlternativeData } from "../alternativesData";

export const entry: AlternativeData = {
  slug: "shortwave",
  name: "Shortwave",
  domain: "shortwave.com",
  category: "email",
  tagline: "AI-powered email client with search and summarization for Gmail",
  painPoints: [
    "Gmail-only; no support for Outlook or other providers",
    "AI features are within the email client, not proactive or cross-tool",
    "Cannot create tasks from email or manage calendar directly",
    "Relatively new; feature set still maturing compared to Superhuman",
    "Requires switching from Gmail's native interface",
  ],
  metaTitle: "Best Shortwave Alternative in 2026 | GAIA",
  metaDescription:
    "Shortwave stays inside your email. GAIA is a proactive AI assistant that connects email, calendar, and tasks across all your tools. Free tier + self-hosting.",
  keywords: [
    "shortwave alternative",
    "best shortwave alternative",
    "shortwave email replacement",
    "ai gmail assistant",
    "shortwave vs gaia",
    "proactive email ai",
    "free shortwave alternative",
    "open source shortwave alternative",
    "self-hosted shortwave alternative",
    "shortwave alternative for individuals",
    "shortwave alternative 2026",
    "AI email triage",
    "inbox zero AI",
    "email management AI",
  ],
  whyPeopleLook:
    "Shortwave brings AI to Gmail with smart summaries, pinned threads, and fast search. It is a thoughtfully designed product but it remains an email client — its AI intelligence does not extend to your calendar, tasks, or other tools. Users who want their AI to manage more than just their inbox find that Shortwave is a stepping stone rather than a destination.",
  gaiaFitScore: 4,
  gaiaReplaces: [
    "Email summarization and thread digests",
    "Priority inbox identification with proactive surfacing",
    "Task creation from email without leaving your workflow",
    "Calendar event scheduling from email content",
    "Cross-tool AI that connects email to tasks and meetings",
  ],
  gaiaAdvantages: [
    "Proactive cross-tool intelligence beyond what an email client can provide",
    "Tasks and calendar integrated natively alongside email",
    "Works from any interface — web, desktop, mobile, CLI, and bots",
    "Open-source and self-hostable for privacy-conscious users",
    "Free tier available without interface lock-in",
  ],
  migrationSteps: [
    "Connect GAIA directly to Gmail via OAuth — use Gmail's native interface alongside",
    "Configure GAIA's inbox monitoring for proactive email surfacing",
    "Enable email-to-task creation for action-requiring threads",
    "Link Google Calendar for complete inbox-to-calendar automation",
  ],
  faqs: [
    {
      question: "Does GAIA replace the Gmail interface like Shortwave?",
      answer:
        "GAIA does not replace the Gmail interface. It works alongside Gmail, managing your inbox proactively and taking actions on your behalf. You can continue using Gmail's UI while GAIA handles the intelligent layer.",
    },
    {
      question: "Can GAIA summarize emails like Shortwave?",
      answer:
        "Yes. GAIA can summarize email threads, generate daily inbox digests, and provide contextual summaries of important conversations — with the added ability to create tasks and calendar events from those summaries.",
    },
    {
      question: "Is GAIA better for productivity than Shortwave?",
      answer:
        "For end-to-end productivity — email plus calendar plus tasks plus automation — GAIA is more capable. Shortwave is better if you primarily want a polished email client with smart features.",
    },
    {
      question: "Does GAIA have IMAP/SMTP support like an email client?",
      answer:
        "GAIA connects to Gmail via the Gmail API rather than IMAP/SMTP. It is not an email client but an AI layer on top of your existing email account.",
    },
  ],
};
