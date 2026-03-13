import type { AlternativeData } from "../alternativesData";

export const entry: AlternativeData = {
  slug: "logseq",
  name: "Logseq",
  domain: "logseq.com",
  category: "notes",
  tagline: "Open-source, local-first outliner with bidirectional linking",
  painPoints: [
    "Outliner format is polarizing — not everyone thinks in bullet hierarchies",
    "Performance degrades significantly with large graphs",
    "Sync is limited and the mobile experience is unreliable",
    "No proactive AI or automation for capturing information automatically",
    "Requires manual maintenance to keep the graph useful",
  ],
  metaTitle: "Best Logseq Alternative in 2026 | GAIA",
  metaDescription:
    "Logseq requires manual note maintenance and has no proactive AI. GAIA is a proactive AI assistant with built-in graph memory. Free tier + open-source self-hosting.",
  keywords: [
    "logseq alternative",
    "best logseq alternative",
    "logseq replacement",
    "open source knowledge ai",
    "logseq vs gaia",
    "ai personal knowledge base",
    "free logseq alternative",
    "open source logseq alternative",
    "self-hosted logseq alternative",
    "logseq alternative for individuals",
    "logseq alternative 2026",
    "AI second brain",
    "open source PKM",
    "self-hosted note taking",
  ],
  whyPeopleLook:
    "Logseq's open-source, local-first approach to networked thought has attracted users who want privacy and data ownership alongside bidirectional linking. But like Obsidian, Logseq demands constant manual input. Every note, link, and tag is your responsibility. Performance issues with large graphs and a buggy mobile experience have driven many users to seek alternatives — particularly ones that combine knowledge management with proactive AI assistance.",
  gaiaFitScore: 3,
  gaiaReplaces: [
    "Automatic knowledge graph construction from email and calendar data",
    "Semantic search over personal knowledge without manual tagging",
    "Meeting note capture without manual journaling",
    "Context surfacing during tasks without searching your graph manually",
  ],
  gaiaAdvantages: [
    "Knowledge is captured automatically without manual journal entries",
    "Consistent mobile and sync experience across all platforms",
    "Proactive intelligence surfaces relevant knowledge without searching",
    "Email and calendar context enriches the knowledge graph automatically",
    "Open-source and self-hostable like Logseq",
  ],
  migrationSteps: [
    "Export your Logseq database as Markdown or JSON",
    "Import key notes into GAIA's memory for semantic retrieval",
    "Connect Gmail and Google Calendar to automatically enrich GAIA's memory",
    "Use GAIA's query interface to retrieve knowledge instead of manual graph navigation",
  ],
  faqs: [
    {
      question: "Does GAIA support Markdown like Logseq?",
      answer:
        "GAIA can read and process Markdown files from your Logseq export. It does not provide a Logseq-style outliner interface but can answer questions and surface information from ingested Markdown notes.",
    },
    {
      question: "Is GAIA open-source like Logseq?",
      answer:
        "Yes. Both GAIA and Logseq are fully open-source. GAIA's GitHub repository is publicly available and accepts community contributions.",
    },
    {
      question: "Does GAIA have better mobile support than Logseq?",
      answer:
        "GAIA's React Native mobile app provides a more reliable mobile experience than Logseq's mobile client, which has historically had sync and performance issues.",
    },
    {
      question: "Can GAIA replace Logseq for daily journaling?",
      answer:
        "GAIA can capture daily context automatically from your email and calendar, but it does not provide a journaling interface for free-form writing. If daily journaling is central to your workflow, Logseq or Obsidian may still be valuable alongside GAIA.",
    },
  ],
};
