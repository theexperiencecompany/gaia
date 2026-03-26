/**
 * Comparison pages data — `/compare/[slug]`
 *
 * Each entry generates a page at heygaia.io/compare/{slug} comparing GAIA to a competitor.
 *
 * ## Architecture
 * - Interface: `ComparisonData` — the shape every entry must match
 * - Record: `comparisons` — keyed by slug (e.g. `"notion"`, `"chatgpt"`)
 * - Individual source files: `entries/{slug}.ts` — edit these to update an entry
 * - Helper exports: `getComparison(slug)`, `getAllComparisonSlugs()`, `getAllComparisons()`
 *
 * ## Adding a new comparison
 * 1. Create `entries/{slug}.ts` with `export const entry: ComparisonData = { ... }`
 * 2. Add the entry object here under the slug key in the `comparisons` Record
 * 3. The sitemap picks it up automatically via `getAllComparisonSlugs()`
 *
 * ## Keyword strategy
 * - Lead meta titles with the competitor name (not "GAIA vs X") — searchers look up the competitor
 * - Target "[competitor] alternative with [GAIA differentiator]" as the primary keyword angle
 * - Focus on long-tail: "free X alternative", "open source X alternative", "self-hosted X alternative"
 * - See `.agents/plans/programmatic-seo-plan.md` for the full keyword strategy
 */
export interface ComparisonFeatureRow {
  [key: string]: string;
  feature: string;
  gaia: string;
  competitor: string;
}

export interface ComparisonData {
  slug: string;
  name: string;
  tagline: string;
  description: string;
  metaTitle: string;
  metaDescription: string;
  keywords: string[];
  intro: string;
  rows: ComparisonFeatureRow[];
  gaiaAdvantages: string[];
  competitorAdvantages: string[];
  domain: string;
  verdict: string;
  faqs: Array<{ question: string; answer: string }>;
  relatedPersonas?: string[]; // persona slugs e.g. ["engineering-managers", "product-managers"]
}

import { entry as activepieces } from "./entries/activepieces";
import { entry as airtable } from "./entries/airtable";
import { entry as akiflow } from "./entries/akiflow";
import { entry as anydo } from "./entries/anydo";
import { entry as appleReminders } from "./entries/apple-reminders";
import { entry as asana } from "./entries/asana";
import { entry as bardeen } from "./entries/bardeen";
import { entry as basecamp } from "./entries/basecamp";
import { entry as bear } from "./entries/bear";
import { entry as cal } from "./entries/cal";
import { entry as calendly } from "./entries/calendly";
import { entry as capacities } from "./entries/capacities";
import { entry as chatgpt } from "./entries/chatgpt";
import { entry as chatgptEnterprise } from "./entries/chatgpt-enterprise";
import { entry as chatgptTeams } from "./entries/chatgpt-teams";
import { entry as claude } from "./entries/claude";
import { entry as clickup } from "./entries/clickup";
import { entry as clockify } from "./entries/clockify";
import { entry as clockwise } from "./entries/clockwise";
import { entry as coda } from "./entries/coda";
import { entry as confluence } from "./entries/confluence";
import { entry as copilot } from "./entries/copilot";
import { entry as craft } from "./entries/craft";
import { entry as cursorAi } from "./entries/cursor-ai";
import { entry as deepseek } from "./entries/deepseek";
import { entry as discord } from "./entries/discord";
import { entry as evernote } from "./entries/evernote";
import { entry as fantastical } from "./entries/fantastical";
import { entry as fathom } from "./entries/fathom";
import { entry as figma } from "./entries/figma";
import { entry as firefliesAi } from "./entries/fireflies-ai";
import { entry as focusmate } from "./entries/focusmate";
import { entry as forest } from "./entries/forest";
import { entry as gemini } from "./entries/gemini";
import { entry as googleAssistant } from "./entries/google-assistant";
import { entry as googleCalendar } from "./entries/google-calendar";
import { entry as grammarly } from "./entries/grammarly";
import { entry as granola } from "./entries/granola";
import { entry as grok } from "./entries/grok";
import { entry as harvest } from "./entries/harvest";
import { entry as height } from "./entries/height";
import { entry as heyEmail } from "./entries/hey-email";
import { entry as hubspot } from "./entries/hubspot";
import { entry as iaWriter } from "./entries/ia-writer";
import { entry as jira } from "./entries/jira";
import { entry as lark } from "./entries/lark";
import { entry as limitlessAi } from "./entries/limitless-ai";
import { entry as lindyAi } from "./entries/lindy-ai";
import { entry as linear } from "./entries/linear";
import { entry as logseq } from "./entries/logseq";
import { entry as loom } from "./entries/loom";
import { entry as make } from "./entries/make";
import { entry as martinAi } from "./entries/martin-ai";
import { entry as memAi } from "./entries/mem-ai";
import { entry as miro } from "./entries/miro";
import { entry as missive } from "./entries/missive";
import { entry as monday } from "./entries/monday";
import { entry as motion } from "./entries/motion";
import { entry as n8n } from "./entries/n8n";
import { entry as notion } from "./entries/notion";
import { entry as notionAi } from "./entries/notion-ai";
import { entry as notionCalendar } from "./entries/notion-calendar";
import { entry as nuclino } from "./entries/nuclino";
import { entry as obsidian } from "./entries/obsidian";
import { entry as omnifocus } from "./entries/omnifocus";
import { entry as onenote } from "./entries/onenote";
import { entry as openclaw } from "./entries/openclaw";
import { entry as otterAi } from "./entries/otter-ai";
import { entry as perplexity } from "./entries/perplexity";
import { entry as piAi } from "./entries/pi-ai";
import { entry as pipedream } from "./entries/pipedream";
import { entry as pipedrive } from "./entries/pipedrive";
import { entry as poke } from "./entries/poke";
import { entry as quip } from "./entries/quip";
import { entry as reclaim } from "./entries/reclaim";
import { entry as reflectApp } from "./entries/reflect-app";
import { entry as relay } from "./entries/relay";
import { entry as rescuetime } from "./entries/rescuetime";
import { entry as rewindAi } from "./entries/rewind-ai";
import { entry as roamResearch } from "./entries/roam-research";
import { entry as sanebox } from "./entries/sanebox";
import { entry as savvycal } from "./entries/savvycal";
import { entry as shortwave } from "./entries/shortwave";
import { entry as smartsheet } from "./entries/smartsheet";
import { entry as spark } from "./entries/spark";
import { entry as sunsama } from "./entries/sunsama";
import { entry as superhuman } from "./entries/superhuman";
import { entry as tana } from "./entries/tana";
import { entry as teams } from "./entries/teams";
import { entry as things3 } from "./entries/things3";
import { entry as ticktick } from "./entries/ticktick";
import { entry as todoist } from "./entries/todoist";
import { entry as toggl } from "./entries/toggl";
import { entry as trello } from "./entries/trello";
import { entry as ulysses } from "./entries/ulysses";
import { entry as whimsical } from "./entries/whimsical";
import { entry as wrike } from "./entries/wrike";
import { entry as zapier } from "./entries/zapier";
import { entry as zoho } from "./entries/zoho";
import { entry as zoom } from "./entries/zoom";

export const comparisons: Record<string, ComparisonData> = {
  [activepieces.slug]: activepieces,
  [airtable.slug]: airtable,
  [akiflow.slug]: akiflow,
  [anydo.slug]: anydo,
  [appleReminders.slug]: appleReminders,
  [asana.slug]: asana,
  [bardeen.slug]: bardeen,
  [basecamp.slug]: basecamp,
  [bear.slug]: bear,
  [cal.slug]: cal,
  [calendly.slug]: calendly,
  [capacities.slug]: capacities,
  [chatgptEnterprise.slug]: chatgptEnterprise,
  [chatgptTeams.slug]: chatgptTeams,
  [chatgpt.slug]: chatgpt,
  [claude.slug]: claude,
  [clickup.slug]: clickup,
  [clockify.slug]: clockify,
  [clockwise.slug]: clockwise,
  [coda.slug]: coda,
  [confluence.slug]: confluence,
  [copilot.slug]: copilot,
  [craft.slug]: craft,
  [cursorAi.slug]: cursorAi,
  [deepseek.slug]: deepseek,
  [discord.slug]: discord,
  [evernote.slug]: evernote,
  [fantastical.slug]: fantastical,
  [fathom.slug]: fathom,
  [figma.slug]: figma,
  [firefliesAi.slug]: firefliesAi,
  [focusmate.slug]: focusmate,
  [forest.slug]: forest,
  [gemini.slug]: gemini,
  [googleAssistant.slug]: googleAssistant,
  [googleCalendar.slug]: googleCalendar,
  [grammarly.slug]: grammarly,
  [granola.slug]: granola,
  [grok.slug]: grok,
  [harvest.slug]: harvest,
  [height.slug]: height,
  [heyEmail.slug]: heyEmail,
  [hubspot.slug]: hubspot,
  [iaWriter.slug]: iaWriter,
  [jira.slug]: jira,
  [lark.slug]: lark,
  [limitlessAi.slug]: limitlessAi,
  [lindyAi.slug]: lindyAi,
  [linear.slug]: linear,
  [logseq.slug]: logseq,
  [loom.slug]: loom,
  [make.slug]: make,
  [martinAi.slug]: martinAi,
  [memAi.slug]: memAi,
  [miro.slug]: miro,
  [missive.slug]: missive,
  [monday.slug]: monday,
  [motion.slug]: motion,
  [n8n.slug]: n8n,
  [notionAi.slug]: notionAi,
  [notionCalendar.slug]: notionCalendar,
  [notion.slug]: notion,
  [nuclino.slug]: nuclino,
  [obsidian.slug]: obsidian,
  [omnifocus.slug]: omnifocus,
  [onenote.slug]: onenote,
  [openclaw.slug]: openclaw,
  [otterAi.slug]: otterAi,
  [perplexity.slug]: perplexity,
  [piAi.slug]: piAi,
  [pipedream.slug]: pipedream,
  [pipedrive.slug]: pipedrive,
  [poke.slug]: poke,
  [quip.slug]: quip,
  [reclaim.slug]: reclaim,
  [reflectApp.slug]: reflectApp,
  [relay.slug]: relay,
  [rescuetime.slug]: rescuetime,
  [rewindAi.slug]: rewindAi,
  [roamResearch.slug]: roamResearch,
  [sanebox.slug]: sanebox,
  [savvycal.slug]: savvycal,
  [shortwave.slug]: shortwave,
  [smartsheet.slug]: smartsheet,
  [spark.slug]: spark,
  [sunsama.slug]: sunsama,
  [superhuman.slug]: superhuman,
  [tana.slug]: tana,
  [teams.slug]: teams,
  [things3.slug]: things3,
  [ticktick.slug]: ticktick,
  [todoist.slug]: todoist,
  [toggl.slug]: toggl,
  [trello.slug]: trello,
  [ulysses.slug]: ulysses,
  [whimsical.slug]: whimsical,
  [wrike.slug]: wrike,
  [zapier.slug]: zapier,
  [zoho.slug]: zoho,
  [zoom.slug]: zoom,
};

export function getComparison(slug: string): ComparisonData | undefined {
  return comparisons[slug];
}

export function getAllComparisonSlugs(): string[] {
  return Object.keys(comparisons);
}

export function getAllComparisons(): ComparisonData[] {
  return Object.values(comparisons);
}
