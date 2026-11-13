/**
 * Which `tool_data` entries become a bot card, and how — the bot counterpart of
 * the web's tool renderers. A tool without a builder is not shown on bots; the
 * agent's own reply covers it.
 *
 * @module
 */

import type { ReportedBotCard } from "../../api/generated";
import { APPROVAL_REQUEST_TOOL_NAME } from "../../chat/approvals";
import type { RateLimitData } from "../../chat/types";
import type { IntegrationConnectionData } from "../../types/integrations";
import { wideLog } from "../utils/wide-events";
import { buildApprovalCards, isApprovalPosted } from "./builders/approval";
import { buildCalendarFetchCards } from "./builders/calendar-fetch";
import { buildChartCards } from "./builders/chart";
import { buildCodeCards, isCodePosted } from "./builders/code";
import {
  buildDeepResearchCards,
  isDeepResearchPosted,
} from "./builders/deep-research";
import { buildDeviceApprovalCards } from "./builders/device-approval";
import { buildDeviceOnboardingCards } from "./builders/device-onboarding";
import { buildEmailComposeCards } from "./builders/email-compose";
import { buildEmailThreadCards } from "./builders/email-thread";
import { buildIntegrationConnectionCards } from "./builders/integration-connection";
import { buildRateLimitCards } from "./builders/rate-limit";
import { buildSearchResultsCards } from "./builders/search-results";
import { buildSupportTicketCards } from "./builders/support-ticket";
import { buildTwitterSearchCards } from "./builders/twitter-search";
import { buildTwitterUserCards } from "./builders/twitter-user";
import { buildWeatherCards } from "./builders/weather";
import { buildWorkflowCreatedCards } from "./builders/workflow-created";
import { buildWorkflowDraftCards } from "./builders/workflow-draft";
import { renderCardText } from "./render-text";
import type { Card } from "./types";

/** The payload each carded tool streams, keyed by its `tool_name`. */
interface CardToolDataMap {
  integration_connection_required: IntegrationConnectionData;
  [APPROVAL_REQUEST_TOOL_NAME]: Parameters<typeof buildApprovalCards>[0];
  rate_limit_data: RateLimitData;
  email_compose_data: Parameters<typeof buildEmailComposeCards>[0];
  email_thread_data: Parameters<typeof buildEmailThreadCards>[0];
  calendar_fetch_data: Parameters<typeof buildCalendarFetchCards>[0];
  search_results: Parameters<typeof buildSearchResultsCards>[0];
  deep_research_results: Parameters<typeof buildDeepResearchCards>[0];
  weather_data: Parameters<typeof buildWeatherCards>[0];
  twitter_user_data: Parameters<typeof buildTwitterUserCards>[0];
  twitter_search_data: Parameters<typeof buildTwitterSearchCards>[0];
  code_data: Parameters<typeof buildCodeCards>[0];
  chart_data: Parameters<typeof buildChartCards>[0];
  device_onboarding_required: Parameters<typeof buildDeviceOnboardingCards>[0];
  device_approval_required: Parameters<typeof buildDeviceApprovalCards>[0];
  workflow_draft: Parameters<typeof buildWorkflowDraftCards>[0];
  workflow_created: Parameters<typeof buildWorkflowCreatedCards>[0];
  support_ticket_data: Parameters<typeof buildSupportTicketCards>[0];
}

type CardToolName = keyof CardToolDataMap;

/** How one carded tool's payload becomes cards. */
interface CardTool<Data> {
  /** Every state of the payload, including the one a tap leaves it in. */
  build: (data: Data) => Card[];
  /**
   * Whether a streamed or queued payload is posted as a new card; every
   * payload is when absent. A tap's update re-renders a card regardless.
   */
  isPosted?: (data: Data) => boolean;
}

const CARD_TOOLS: { [K in CardToolName]: CardTool<CardToolDataMap[K]> } = {
  integration_connection_required: { build: buildIntegrationConnectionCards },
  [APPROVAL_REQUEST_TOOL_NAME]: {
    build: buildApprovalCards,
    isPosted: isApprovalPosted,
  },
  rate_limit_data: { build: buildRateLimitCards },
  email_compose_data: { build: buildEmailComposeCards },
  email_thread_data: { build: buildEmailThreadCards },
  calendar_fetch_data: { build: buildCalendarFetchCards },
  search_results: { build: buildSearchResultsCards },
  deep_research_results: {
    build: buildDeepResearchCards,
    isPosted: isDeepResearchPosted,
  },
  weather_data: { build: buildWeatherCards },
  twitter_user_data: { build: buildTwitterUserCards },
  twitter_search_data: { build: buildTwitterSearchCards },
  code_data: { build: buildCodeCards, isPosted: isCodePosted },
  chart_data: { build: buildChartCards },
  device_onboarding_required: { build: buildDeviceOnboardingCards },
  device_approval_required: { build: buildDeviceApprovalCards },
  workflow_draft: { build: buildWorkflowDraftCards },
  workflow_created: { build: buildWorkflowCreatedCards },
  support_ticket_data: { build: buildSupportTicketCards },
};

/** Every tool a bot renders as a card: what each bot registers with the API at startup. */
export const CARD_TOOL_NAMES: readonly string[] = Object.keys(CARD_TOOLS);

function isCardToolName(name: string): name is CardToolName {
  return Object.hasOwn(CARD_TOOLS, name);
}

/** The two fields of a `tool_data` entry a card is built from. */
export interface CardSourceEntry {
  tool_name: string;
  data?: unknown;
}

/** The tool behind an entry, or `null` when bots don't show it. */
function cardToolFor(entry: CardSourceEntry): CardTool<unknown> | null {
  if (!isCardToolName(entry.tool_name)) return null;
  // The API owns these payloads' shape; `tool_name` is what selects it.
  return CARD_TOOLS[entry.tool_name] as CardTool<unknown>;
}

/**
 * Builds an entry's cards and their text, or none when its payload is not the
 * shape the builder expects. Rendering the text walks every block, so a card
 * that cannot be drawn never leaves here. Logged as an error: the card is lost,
 * but the reply the user is waiting on still arrives, which one bad payload
 * must never stop.
 */
function buildCards(
  tool: CardTool<unknown>,
  entry: CardSourceEntry,
  posting: boolean,
): ToolCard[] {
  try {
    if (posting && tool.isPosted && !tool.isPosted(entry.data)) return [];
    return tool.build(entry.data).map((card) => ({
      tool_name: entry.tool_name,
      card,
      text: renderCardText(card),
    }));
  } catch (error) {
    wideLog.error("card_build_failed", { tool_name: entry.tool_name }, error);
    return [];
  }
}

/**
 * The card a tap's updated entry renders for the message that was tapped. An
 * entry can build several cards (one per email draft): the tapped one holds the
 * tapped action id. `null` when no single card can be told apart.
 */
export function cardAfterTap(
  entry: CardSourceEntry,
  actionId: string,
): Card | null {
  const tool = cardToolFor(entry);
  const cards = tool
    ? buildCards(tool, entry, false).map(({ card }) => card)
    : [];
  if (cards.length === 1) return cards[0];
  return cards.find((card) => card.actionIds?.includes(actionId)) ?? null;
}

/** A card built from one entry, with the text that records it. */
export interface ToolCard {
  tool_name: string;
  card: Card;
  /** {@link renderCardText} of the card: what the agent's record says was shown. */
  text: string;
}

/** The cards posted for one streamed or queued entry; none when bots don't show it. */
export function toolCardsFor(entry: CardSourceEntry): ToolCard[] {
  const tool = cardToolFor(entry);
  return tool ? buildCards(tool, entry, true) : [];
}

/** How one card's delivery is reported to the API. */
export function deliveryEntry(
  toolCard: ToolCard,
  delivered: boolean,
): ReportedBotCard {
  return { tool_name: toolCard.tool_name, text: toolCard.text, delivered };
}
