import type { DocsGuideLink } from "../index";

import { COMPARE_DOCS_LINKS } from "./compare-links";

/**
 * Alternative-to pages link the same docs guides as their compare
 * counterparts: same tool, same exact-intent guides. Single source of
 * truth lives in compare-links.ts.
 */
const ALTERNATIVE_SLUGS: readonly string[] = [
  "akiflow",
  "anydo",
  "asana",
  "bardeen",
  "basecamp",
  "bee",
  "calendly",
  "chatgpt",
  "chatgpt-atlas",
  "clickup",
  "clockwise",
  "copilot",
  "dot-app",
  "fantastical",
  "friend-pendant",
  "gemini",
  "gemini-assistant",
  "google-assistant",
  "google-calendar",
  "hey-email",
  "instinct",
  "jira",
  "limitless-ai",
  "lindy-ai",
  "linear",
  "make",
  "mem-ai",
  "missive",
  "monday",
  "motion",
  "n8n",
  "notion",
  "notion-ai",
  "omi",
  "omnifocus",
  "openai-dots",
  "openclaw",
  "perplexity",
  "pipedream",
  "poke",
  "reclaim",
  "relay",
  "sanebox",
  "shortwave",
  "siri",
  "spark",
  "sunsama",
  "superhuman",
  "things3",
  "ticktick",
  "todoist",
  "trello",
  "zapier",
];

export const ALTERNATIVE_DOCS_LINKS: Record<string, readonly DocsGuideLink[]> =
  Object.fromEntries(
    ALTERNATIVE_SLUGS.flatMap((slug): [string, readonly DocsGuideLink[]][] =>
      slug in COMPARE_DOCS_LINKS ? [[slug, COMPARE_DOCS_LINKS[slug]]] : [],
    ),
  );
