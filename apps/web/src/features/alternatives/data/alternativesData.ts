/**
 * Alternative-to pages data — `/alternative-to/[slug]`
 *
 * Each entry generates a page at heygaia.io/alternative-to/{slug} targeting
 * "best [product] alternative" searches from users ready to switch.
 *
 * ## Architecture
 * - Interface: `AlternativeData` — the shape every entry must match
 * - Individual source files: `entries/{slug}.ts` — edit these to update an entry
 * - Exports: `getAllAlternatives()`, `getAlternative(slug)`, `getAllAlternativeSlugs()`, `getAlternativesByCategory(category)`
 *
 * ## Keyword strategy
 * - Primary: "[product] alternative 2026"
 * - Modifiers: "free [product] alternative", "open source [product] alternative", "self-hosted [product] alternative"
 * - GAIA differentiators: open source, self-hostable, free tier, proactive AI, 50+ integrations
 *
 * ## Adding a new entry
 * 1. Create `entries/{slug}.ts` with `export const entry: AlternativeData = { ... }`
 * 2. Import the entry below and add it to the `alternatives` array in the same order
 * 3. The sitemap picks it up automatically via `getAllAlternativeSlugs()`
 */
export interface AlternativeData {
  slug: string;
  name: string;
  domain: string;
  category:
    | "task-manager"
    | "ai-assistant"
    | "calendar"
    | "email"
    | "automation"
    | "notes"
    | "productivity-suite";
  tagline: string;
  painPoints: string[];
  metaTitle: string;
  metaDescription: string;
  keywords: string[];
  whyPeopleLook: string;
  gaiaFitScore: number;
  gaiaReplaces: string[];
  gaiaAdvantages: string[];
  migrationSteps: string[];
  faqs: Array<{ question: string; answer: string }>;
  comparisonRows?: Array<{
    feature: string;
    gaia: string;
    competitor: string;
  }>;
}

import { entry as airtable } from "./entries/airtable";
import { entry as akiflow } from "./entries/akiflow";
import { entry as anydo } from "./entries/anydo";
import { entry as asana } from "./entries/asana";
import { entry as bardeen } from "./entries/bardeen";
import { entry as basecamp } from "./entries/basecamp";
import { entry as bear } from "./entries/bear";
import { entry as calendly } from "./entries/calendly";
import { entry as capacities } from "./entries/capacities";
import { entry as chatgpt } from "./entries/chatgpt";
import { entry as clickup } from "./entries/clickup";
import { entry as clockwise } from "./entries/clockwise";
import { entry as coda } from "./entries/coda";
import { entry as copilot } from "./entries/copilot";
import { entry as craft } from "./entries/craft";
import { entry as evernote } from "./entries/evernote";
import { entry as fantastical } from "./entries/fantastical";
import { entry as gemini } from "./entries/gemini";
import { entry as googleAssistant } from "./entries/google-assistant";
import { entry as googleCalendar } from "./entries/google-calendar";
import { entry as heyEmail } from "./entries/hey-email";
import { entry as jira } from "./entries/jira";
import { entry as limitlessAi } from "./entries/limitless-ai";
import { entry as lindyAi } from "./entries/lindy-ai";
import { entry as linear } from "./entries/linear";
import { entry as logseq } from "./entries/logseq";
import { entry as make } from "./entries/make";
import { entry as memAi } from "./entries/mem-ai";
import { entry as missive } from "./entries/missive";
import { entry as monday } from "./entries/monday";
import { entry as motion } from "./entries/motion";
import { entry as n8n } from "./entries/n8n";
import { entry as notion } from "./entries/notion";
import { entry as notionAi } from "./entries/notion-ai";
import { entry as obsidian } from "./entries/obsidian";
import { entry as omnifocus } from "./entries/omnifocus";
import { entry as perplexity } from "./entries/perplexity";
import { entry as pipedream } from "./entries/pipedream";
import { entry as reclaim } from "./entries/reclaim";
import { entry as reflectApp } from "./entries/reflect-app";
import { entry as relay } from "./entries/relay";
import { entry as roamResearch } from "./entries/roam-research";
import { entry as sanebox } from "./entries/sanebox";
import { entry as shortwave } from "./entries/shortwave";
import { entry as spark } from "./entries/spark";
import { entry as sunsama } from "./entries/sunsama";
import { entry as superhuman } from "./entries/superhuman";
import { entry as tana } from "./entries/tana";
import { entry as things3 } from "./entries/things3";
import { entry as ticktick } from "./entries/ticktick";
import { entry as todoist } from "./entries/todoist";
import { entry as trello } from "./entries/trello";
import { entry as zapier } from "./entries/zapier";

export const alternatives: AlternativeData[] = [
  // Productivity suites
  notion,
  monday,
  asana,
  clickup,
  trello,
  jira,
  basecamp,

  // AI assistants
  chatgpt,
  copilot,
  gemini,
  googleAssistant,

  // Calendar/time
  motion,
  reclaim,
  clockwise,
  fantastical,
  calendly,

  // Email
  superhuman,
  sanebox,
  shortwave,

  // Task managers
  todoist,
  ticktick,
  things3,
  anydo,

  // Automation
  zapier,
  make,
  n8n,
  bardeen,

  // Notes/knowledge
  obsidian,
  logseq,
  memAi,
  reflectApp,

  // AI assistants (additional)
  notionAi,

  // Productivity suites (additional)
  evernote,
  bear,
  craft,
  coda,
  airtable,

  // Task managers (additional)
  sunsama,
  akiflow,

  // Email (additional)
  spark,
  missive,

  // Automation (additional)
  pipedream,
  relay,

  // Notes/PKM (additional)
  capacities,
  tana,

  // Calendar (additional)
  googleCalendar,

  // Task managers (additional)
  linear,

  // Email (additional)
  heyEmail,

  // Task managers (additional)
  omnifocus,

  // AI assistants (additional)
  limitlessAi,
  lindyAi,
  perplexity,

  // Notes/PKM (additional)
  roamResearch,
];

export function getAllAlternatives(): AlternativeData[] {
  return alternatives;
}

export function getAlternative(slug: string): AlternativeData | undefined {
  return alternatives.find((a) => a.slug === slug);
}

export function getAllAlternativeSlugs(): string[] {
  return alternatives.map((a) => a.slug);
}

export function getAlternativesByCategory(
  category: AlternativeData["category"],
): AlternativeData[] {
  return alternatives.filter((a) => a.category === category);
}
