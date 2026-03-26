import type { AlternativeData } from "../alternativesData";

export const entry: AlternativeData = {
  slug: "roam-research",
  name: "Roam Research",
  domain: "roamresearch.com",
  category: "notes",
  tagline:
    "Networked thought for PKM enthusiasts — but your knowledge graph shouldn't require daily feeding",
  painPoints: [
    "Roam requires you to manually capture everything — it has no email integration, calendar sync, or automatic knowledge enrichment from your digital activity",
    "The learning curve is steep: block references, bidirectional links, Clojure-based plugins, and daily note discipline take weeks to master",
    "At $15/month, Roam is expensive compared to free alternatives like Obsidian, yet offers no AI capabilities",
    "Roam is web-only with limited offline support — a significant drawback for users who need mobile or desktop-native experiences",
    "The knowledge graph is only as good as your capture discipline; missed meetings and unlogged emails leave gaps that passive tools would have filled automatically",
  ],
  metaTitle:
    "Roam Research Alternative | GAIA — AI Knowledge Assistant That Builds Its Own Graph",
  metaDescription:
    "Tired of manually feeding Roam Research? GAIA is an open-source AI assistant with graph-based memory that builds itself from your email, calendar, and meetings — no daily notes ritual required.",
  keywords: [
    "roam research alternative",
    "roam research alternative free",
    "roam research alternative reddit",
    "roam research alternative open source",
    "roam alternative",
    "obsidian vs roam research",
    "roam research replacement",
    "roam research alternative 2026",
  ],
  whyPeopleLook:
    "Roam Research attracted PKM enthusiasts with the promise of a self-building knowledge graph, but the reality is that Roam only knows what you manually type into it. Users grow frustrated with the $15/month price for a tool that requires significant daily discipline to deliver value, especially when free alternatives like Obsidian offer similar bidirectional linking. The deeper frustration is that Roam's graph is entirely manual — it doesn't capture anything from your email, calendar, or meetings on its own.",
  gaiaFitScore: 3,
  gaiaReplaces: [
    "Manual daily notes logging in Roam to capture what happened today",
    "Copy-pasting email action items and meeting notes into Roam blocks",
    "Building Roam queries to surface tasks and deadlines",
    "Maintaining Roam as a separate tool alongside a task manager and email client",
  ],
  gaiaAdvantages: [
    "GAIA's graph-based memory builds itself from your email, calendar, and meeting data — no manual capture required",
    "Tasks, emails, and calendar events are linked automatically without block references or daily note discipline",
    "Open source and self-hostable; Roam is a closed SaaS at $15/month",
    "GAIA adds action to knowledge: it creates tasks, drafts emails, and updates calendar from the context it captures",
    "Free tier available; Roam has no free plan",
  ],
  migrationSteps: [
    "Export your Roam graph as JSON or Markdown to preserve your existing notes and links",
    "Import key project notes and reference content into GAIA's memory system",
    "Connect Gmail and Google Calendar so GAIA begins enriching its graph automatically from your digital activity",
    "Replace your Roam daily notes habit with GAIA's morning briefing — it surfaces what happened, what's due, and what needs attention without manual logging",
  ],
  faqs: [
    {
      question: "Does GAIA have bidirectional linking like Roam Research?",
      answer:
        "GAIA uses a graph-based memory that automatically infers relationships between people, projects, emails, meetings, and tasks — achieving the connected knowledge goal of bidirectional linking without requiring manual [[bracket]] notation. You don't build the graph; GAIA builds it from your activity.",
    },
    {
      question: "Is GAIA free compared to Roam Research?",
      answer:
        "Roam costs $15/month with no free tier. GAIA has a free tier and is open source — self-hosters can run it for free via Docker. GAIA Pro is $20/month but includes task management, email integration, and calendar coordination alongside knowledge management.",
    },
    {
      question: "Why do people leave Roam Research for Obsidian?",
      answer:
        "The most common reasons are Roam's $15/month cost (Obsidian is free), Obsidian's local file storage (Roam is cloud-only), and Obsidian's larger plugin ecosystem. For users who want AI and active task management on top of PKM, GAIA is the next step beyond both.",
    },
    {
      question: "Can GAIA replace both Roam and my task manager?",
      answer:
        "Yes. GAIA combines automatic knowledge capture with task management, email triage, and calendar coordination — covering the PKM role Roam fills plus the active productivity management that Roam doesn't attempt.",
    },
  ],
};
