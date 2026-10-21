import { siteConfig } from "@/lib/seo";

export type MarketingPageCategory = "Product" | "Resources" | "Company";

export interface MarketingPage {
  path: string;
  title: string;
  description: string;
  category: MarketingPageCategory;
}

/** Static marketing pages listed by /feed.xml and /llms.txt; data-driven pages come from their own getters. */
export const MARKETING_PAGES: readonly MarketingPage[] = [
  {
    path: "",
    title: siteConfig.name,
    description: siteConfig.description,
    category: "Product",
  },
  {
    path: "/features",
    title: "Features",
    description:
      "GAIA features: email triage, calendar automation, todos, workflows and integrations across your tools.",
    category: "Product",
  },
  {
    path: "/pricing",
    title: "Pricing",
    description:
      "Hosted GAIA is one paid Pro plan, with Enterprise for teams; self-hosting is free for non-commercial use.",
    category: "Product",
  },
  {
    path: "/download",
    title: "Download GAIA",
    description:
      "Get the GAIA desktop app for macOS, Windows and Linux, or use GAIA on the web.",
    category: "Product",
  },
  {
    path: "/marketplace",
    title: "Integration Marketplace",
    description:
      "Browse GAIA integrations and MCP servers for Gmail, Slack, Notion, GitHub and more.",
    category: "Product",
  },
  {
    path: "/use-cases",
    title: "Use Cases",
    description: "Ready-made GAIA workflows for email, calendar and tasks.",
    category: "Product",
  },
  {
    path: "/for",
    title: "Who GAIA helps",
    description:
      "How founders, developers, sales teams and more use GAIA as their AI assistant.",
    category: "Product",
  },
  {
    path: "/open-source-ai-assistant",
    title: "Open-source AI assistant",
    description:
      "GAIA's code is source-available (PolyForm Noncommercial) and self-hostable.",
    category: "Product",
  },
  {
    path: "/ai-chief-of-staff",
    title: "AI chief of staff",
    description:
      "GAIA as your AI chief of staff: inbox, calendar and follow-ups handled.",
    category: "Product",
  },
  {
    path: "/inbox-zero-ai",
    title: "Inbox zero with AI",
    description: "Reach inbox zero with GAIA's AI email triage and drafting.",
    category: "Product",
  },
  {
    path: "/ai-assistant-whatsapp-telegram-imessage",
    title: "AI assistant on WhatsApp, Telegram and iMessage",
    description:
      "What GAIA does when you text it, and how to link each chat app.",
    category: "Product",
  },
  {
    path: "/ai-assistant-with-memory",
    title: "AI assistant with memory",
    description:
      "What GAIA remembers about you, and how to view, edit or delete it.",
    category: "Product",
  },
  {
    path: "/ai-assistant-like-jarvis",
    title: "AI assistant like Jarvis",
    description:
      "Proactive workflows, voice, wake word and desktop app, and the limits.",
    category: "Product",
  },
  {
    path: "/ai-assistant-that-can-see-your-screen",
    title: "AI assistant that can see your screen",
    description: "How GAIA's desktop app takes and reads screenshots.",
    category: "Product",
  },
  {
    path: "/ai-assistant-that-uses-your-computer",
    title: "AI assistant that uses your computer",
    description:
      "GAIA's desktop actions and cloud browser tasks, and what it cannot do.",
    category: "Product",
  },
  {
    path: "/blog",
    title: "Blog",
    description: "GAIA blog: productivity, AI assistants and automation.",
    category: "Resources",
  },
  {
    path: "/cli",
    title: "Install GAIA CLI",
    description:
      "Install the GAIA CLI to set up and manage a self-hosted GAIA instance.",
    category: "Resources",
  },
  {
    path: "/learn",
    title: "Learn: AI glossary",
    description:
      "Plain-language definitions of AI and productivity concepts, and how GAIA uses them.",
    category: "Resources",
  },
  {
    path: "/compare",
    title: "Compare AI assistants",
    description:
      "Side-by-side comparisons of GAIA with other AI assistants and productivity tools.",
    category: "Resources",
  },
  {
    path: "/alternative-to",
    title: "GAIA as an alternative",
    description:
      "Why people switch to GAIA from other AI assistants and productivity apps.",
    category: "Resources",
  },
  {
    path: "/automate",
    title: "Automate your tools",
    description: "Guides for connecting pairs of tools with GAIA automations.",
    category: "Resources",
  },
  {
    path: "/best-ai-assistant",
    title: "Best AI assistant",
    description: "What makes GAIA the best AI assistant for getting work done.",
    category: "Resources",
  },
  {
    path: "/best-ai-email-assistant",
    title: "Best AI email assistant",
    description:
      "GAIA ranked against Superhuman, SaneBox, Shortwave, Missive and Spark.",
    category: "Resources",
  },
  {
    path: "/best-ai-calendar-assistant",
    title: "Best AI calendar assistant",
    description:
      "GAIA ranked against Motion, Reclaim, Sunsama, Akiflow and Clockwise.",
    category: "Resources",
  },
  {
    path: "/best-ai-executive-assistant",
    title: "Best AI executive assistant apps",
    description:
      "GAIA ranked against Copilot, Superhuman, Lindy, Motion and other EA tools.",
    category: "Resources",
  },
  {
    path: "/how-to-use-ai-as-a-personal-assistant",
    title: "How to use AI as a personal assistant",
    description: "Step-by-step setup of GAIA as a personal assistant.",
    category: "Resources",
  },
  {
    path: "/faq",
    title: "FAQ",
    description: "Frequently asked questions about GAIA.",
    category: "Company",
  },
  {
    path: "/about",
    title: "About",
    description: "GAIA's mission and the team behind it.",
    category: "Company",
  },
  {
    path: "/manifesto",
    title: "Manifesto",
    description: "Why GAIA exists: a personal AI assistant for everyone.",
    category: "Company",
  },
  {
    path: "/contact",
    title: "Contact",
    description: "Get in touch with the GAIA team.",
    category: "Company",
  },
  {
    path: "/brand",
    title: "Brand assets",
    description: "GAIA logo and brand assets in PNG and SVG.",
    category: "Company",
  },
];
