import type { IntegrationConnectionData } from "../../../types/integrations";
import {
  connectionPromptState,
  PROMPT_ACTION_LABEL,
} from "../../../utils/integrationStatus";
import type { Card, CardLinkAction, CardStatus } from "../types";

const INTEGRATIONS_PAGE_LABEL = "Open integrations";
const API_KEY_LABEL = "Add API key";
/** A key is a secret: it goes into GAIA's own form, never into a chat log. */
const API_KEY_NOTE =
  "It connects with an API key. Add it in GAIA, never paste it here.";

/**
 * A login-free link connects in one tap; without a lifetime the link is the
 * integrations page, where the user signs in to GAIA and connects from there.
 */
function connectAction(
  connectUrl: string,
  data: IntegrationConnectionData,
  fix: string,
): CardLinkAction {
  if (data.needs_api_key) {
    return { kind: "link", label: API_KEY_LABEL, url: connectUrl };
  }
  if (data.connect_url_valid_minutes == null) {
    return { kind: "link", label: INTEGRATIONS_PAGE_LABEL, url: connectUrl };
  }
  return { kind: "link", label: fix, url: connectUrl };
}

function connectionStatus(data: IntegrationConnectionData): CardStatus {
  if (data.needs_api_key) return { label: "API key needed", tone: "warning" };
  if (data.expired) return { label: "Connection expired", tone: "warning" };
  return { label: "Not connected", tone: "info" };
}

function linkLifetime(minutes: number | null | undefined): string | undefined {
  if (minutes == null) return undefined;
  return `Link works for ${minutes} minutes`;
}

/** The `integration_connection_required` card: why, plus the link that fixes it. */
export function buildIntegrationConnectionCards(
  data: IntegrationConnectionData,
): Card[] {
  const name = data.integration_name ?? data.integration_id;
  // No live status on a bot: the payload's own flags decide the verb. The
  // headline is the fix itself ("Reconnect PostHog"); the body says why.
  const fix = data.needs_api_key
    ? `Add your ${name} API key`
    : `${PROMPT_ACTION_LABEL[connectionPromptState(data, undefined)]} ${name}`;
  const card: Card = {
    title: fix,
    accent: data.expired ? "warning" : "brand",
    status: connectionStatus(data),
    blocks: [
      { kind: "text", markdown: data.message },
      ...(data.needs_api_key
        ? [{ kind: "text" as const, markdown: API_KEY_NOTE }]
        : []),
    ],
    actions: data.connect_url
      ? [connectAction(data.connect_url, data, fix)]
      : [],
    footer: data.connect_url
      ? linkLifetime(data.connect_url_valid_minutes)
      : undefined,
  };
  return [card];
}
