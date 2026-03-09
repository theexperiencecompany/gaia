import type { AlternativeData } from "../alternativesData";

export const entry: AlternativeData = {
  slug: "perplexity",
  name: "Perplexity",
  domain: "perplexity.ai",
  category: "ai-assistant",
  tagline:
    "The best AI search engine — but searching the web is very different from managing your life",
  painPoints: [
    "Perplexity answers questions about the world, not about your personal context — it has no access to your email, tasks, calendar, or meeting history",
    "Every interaction starts from scratch: Perplexity has no persistent memory of you, your projects, or your preferences",
    "No task management, no calendar integration, and no email capabilities — it's a research tool, not a productivity assistant",
    "Perplexity Pro is $20/month but is limited to web search and AI answers; it doesn't automate or manage anything",
    "No automation or workflow capabilities — Perplexity surfaces information but never takes action on your behalf",
  ],
  metaTitle:
    "Perplexity Alternative | GAIA — AI Assistant That Manages Your Work, Not Just Searches It",
  metaDescription:
    "Need more than AI search? GAIA is a personal AI assistant that manages your email, tasks, and calendar — with persistent memory and 50+ integrations. Open source, self-hostable, free tier available.",
  keywords: [
    "perplexity alternative",
    "perplexity alternative free",
    "perplexity alternative reddit",
    "perplexity alternative open source",
    "perplexity alternative for research",
    "free perplexity alternative",
    "perplexity ai replacement",
    "perplexity alternative 2026",
  ],
  whyPeopleLook:
    "Users searching for a Perplexity alternative usually fall into two distinct camps: those who want a different research AI (faster, cheaper, or with different citation sources), and those who realize they need an AI that manages their personal productivity rather than answers web questions. GAIA squarely addresses the second group — users who want an AI that knows their inbox, tracks their tasks, and coordinates their calendar, not one that searches the open web.",
  gaiaFitScore: 2,
  gaiaReplaces: [
    "Using Perplexity to find context about your own meetings or projects (GAIA holds this in memory)",
    "Manually acting on Perplexity research results in separate tools",
    "Querying Perplexity for task prioritization advice based on a context it doesn't have",
  ],
  gaiaAdvantages: [
    "Persistent graph-based memory of your email, tasks, calendar, and meetings — Perplexity has no memory of you",
    "GAIA takes action: creates tasks, drafts emails, updates calendar — Perplexity only provides answers",
    "50+ tool integrations connect GAIA to your actual work context vs Perplexity's web-only knowledge",
    "Open source and self-hostable; Perplexity is a closed cloud service",
    "GAIA Pro at $20/month includes full productivity management vs Perplexity Pro's search-only scope",
  ],
  migrationSteps: [
    "Identify the Perplexity use cases that relate to personal productivity (scheduling help, email drafting, task planning) — these map directly to GAIA",
    "Connect GAIA to your Gmail, Google Calendar, and task tools so it has the context Perplexity never had access to",
    "Use GAIA's chat interface for productivity queries — 'What do I have today?', 'Draft a reply to this email', 'Create a task for this meeting follow-up'",
    "Keep Perplexity for external research tasks (GAIA and Perplexity serve different needs and can coexist)",
  ],
  faqs: [
    {
      question: "Is GAIA a Perplexity alternative for research?",
      answer:
        "Only partially. GAIA can answer questions using your personal context (email, tasks, calendar, meeting history) and connected tool data. For open-web research with cited sources, Perplexity remains stronger. The fit score of 2/5 reflects very different use cases.",
    },
    {
      question: "What does GAIA do that Perplexity cannot?",
      answer:
        "GAIA manages your email, creates and tracks tasks, coordinates your calendar, runs automations, and maintains persistent memory of your work context. Perplexity searches the web and answers questions — it cannot manage, automate, or remember.",
    },
    {
      question: "Is there a free Perplexity alternative?",
      answer:
        "GAIA has a free tier and is open source — self-hosters can run it for free. However, if you specifically want AI web search with citations, GAIA is not a direct substitute for Perplexity's core use case.",
    },
    {
      question: "Can GAIA and Perplexity be used together?",
      answer:
        "Yes — they serve complementary roles. Use Perplexity for external research and web questions; use GAIA for managing your personal productivity, inbox, and calendar. Many users find this combination covers both information discovery and task execution.",
    },
  ],
};
