import type { FAQItem } from "./faq";

/**
 * Page-specific FAQ data for GEO optimization.
 * Adding FAQ schema to key pages boosts AI search visibility by up to 40%
 * according to Princeton GEO research.
 */

export const homepageFAQs: FAQItem[] = [
  {
    question: "What is GAIA AI assistant?",
    answer:
      "GAIA is an open-source personal AI assistant that proactively manages your email, calendar, tasks, and workflows across 50+ integrated tools. Unlike reactive chatbots like ChatGPT or Siri, GAIA monitors your digital life 24/7 and takes action before you ask, such as triaging your inbox, scheduling meetings, and creating tasks from emails automatically.",
  },
  {
    question: "How is GAIA different from ChatGPT or other AI assistants?",
    answer:
      "ChatGPT, Claude, and Gemini are conversational AIs that wait for your prompts. GAIA is a proactive productivity operating system that autonomously manages your work. It connects to 50+ tools (Gmail, Slack, Notion, GitHub, etc.), creates and executes tasks, automates multi-step workflows, and maintains persistent memory that learns your work patterns over time.",
  },
  {
    question: "Is GAIA free to use?",
    answer:
      "Yes. GAIA offers a free tier with core features including email automation, calendar management, and task organization. Pro plans start at $20/month with higher usage limits and priority support. You can also self-host GAIA entirely free on your own infrastructure for complete data ownership.",
  },
  {
    question: "What integrations does GAIA support?",
    answer:
      "GAIA supports 50+ integrations including Gmail, Google Calendar, Google Docs, Slack, Notion, GitHub, Linear, Todoist, Asana, ClickUp, Trello, Microsoft Teams, HubSpot, Twitter, LinkedIn, and more. You can also build custom integrations through the Model Context Protocol (MCP) and the community marketplace.",
  },
  {
    question: "Is GAIA open source?",
    answer:
      "Yes. GAIA is fully open source, meaning you can inspect every line of code, contribute to development, and self-host the entire system on your own infrastructure. Your data is never used for model training, and self-hosting gives you complete control over your information.",
  },
];

export const marketplaceFAQs: FAQItem[] = [
  {
    question: "What are MCP integrations?",
    answer:
      "MCP (Model Context Protocol) integrations are standardized connections that allow GAIA to interact with external tools and services. They enable GAIA to read emails, manage calendar events, create documents, and perform actions across your productivity stack through a secure, standardized protocol.",
  },
  {
    question: "How many integrations does GAIA support?",
    answer:
      "GAIA supports 50+ integrations including Gmail, Slack, Notion, GitHub, Linear, Google Calendar, Todoist, Asana, ClickUp, Microsoft Teams, HubSpot, and more. The community marketplace allows anyone to build and share custom MCP integrations.",
  },
  {
    question: "Can I create custom integrations for GAIA?",
    answer:
      "Yes. GAIA supports custom MCP integrations that you can build and publish to the community marketplace. This allows you to connect GAIA to any tool or service with an API, extending its capabilities beyond the built-in integrations.",
  },
  {
    question: "Are GAIA integrations free?",
    answer:
      "All community-built integrations in the marketplace are free to use. You can browse, clone, and customize any integration. The marketplace is community-driven, meaning anyone can contribute integrations for others to use.",
  },
];

export const useCasesFAQs: FAQItem[] = [
  {
    question: "What kind of workflows can GAIA automate?",
    answer:
      "GAIA can automate a wide range of workflows including email triage and response, meeting preparation with briefing documents, task creation from emails and messages, daily digests and summaries, social media management, code review coordination, and multi-step processes that span multiple tools.",
  },
  {
    question: "Can I create my own workflows?",
    answer:
      "Yes. You can describe workflows to GAIA in natural language, and it will configure the automation for you. You can also browse and use community-built workflows from the marketplace, customize them to your needs, and publish your own workflows for others to use.",
  },
  {
    question: "Do workflows require coding?",
    answer:
      "No. GAIA workflows are created through natural language conversation. Simply describe what you want automated, which tools to connect, and what triggers should start the workflow. GAIA handles the technical configuration using its AI-powered workflow engine.",
  },
  {
    question: "How are GAIA workflows different from Zapier or Make.com?",
    answer:
      "Zapier and Make.com use deterministic if-this-then-that rules. GAIA workflows are powered by AI that understands context, reads email content, makes intelligent decisions, and adapts to variations. Instead of defining rigid rules, you describe your intent, and GAIA applies intelligence to handle each situation appropriately.",
  },
];

export const manifestoFAQs: FAQItem[] = [
  {
    question: "Why did you build GAIA?",
    answer:
      "We built GAIA because existing AI assistants like Siri, Alexa, and even ChatGPT are fundamentally reactive, they wait for you to ask and forget between conversations. We envisioned an AI that truly understands your digital life, remembers your preferences, and proactively manages your work. GAIA is the assistant we always wanted but could never find.",
  },
  {
    question: "Why is GAIA open source?",
    answer:
      "We believe personal AI assistants should be transparent, trustworthy, and user-controlled. Open source means you can inspect every line of code that handles your data, verify our privacy claims, contribute improvements, and self-host for complete control. We never train on your data or sell it to third parties.",
  },
  {
    question: "What is GAIA's long-term vision?",
    answer:
      "GAIA aims to be a personal assistant available on every device: web, desktop, mobile, voice, phone calls, and eventually smart glasses. We envision a future where everyone has access to a real AI assistant that handles the digital overhead of modern life, letting people focus on what matters most.",
  },
  {
    question: "Can I self-host GAIA?",
    answer:
      "Yes. GAIA is designed for self-hosting with Docker support. You can run the entire system on your own infrastructure for complete data control, zero recurring costs, and full privacy. Our documentation provides step-by-step guides for self-hosting setup.",
  },
];

export const pricingFAQs: FAQItem[] = [
  {
    question: "What is included in GAIA's free plan?",
    answer:
      "GAIA's free plan includes core features: email automation, calendar management, task organization, basic workflow automation, and access to community integrations. It is designed to let you experience GAIA's proactive productivity capabilities before upgrading.",
  },
  {
    question: "How does GAIA's pricing compare to competitors?",
    answer:
      "GAIA Pro starts at $20/month, comparable to ChatGPT Plus ($20/month) and Motion ($19/month). Unlike these tools, GAIA offers a free tier, self-hosting for $0, and combines capabilities that would otherwise require multiple subscriptions (email management, calendar AI, workflow automation, task management).",
  },
  {
    question: "Can I self-host GAIA for free?",
    answer:
      "Yes. Self-hosting GAIA is completely free with no recurring costs. You maintain full control over your data and infrastructure. The only cost is your own server/hosting. Our Docker-based setup makes deployment straightforward.",
  },
];
