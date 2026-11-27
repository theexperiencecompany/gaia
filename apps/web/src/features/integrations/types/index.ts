/**
 * Integration types the API does not describe: client-side states and stream
 * frames. A catalog entry is the generated `MyIntegrationItem`.
 */

import type {
  AddIntegrationResponse,
  CommunityIntegrationItem,
  CommunityListResponse,
  PublicIntegrationDetailResponse,
} from "@shared/api/generated";

export type {
  CreateCustomIntegrationRequest,
  CreateCustomIntegrationResponse,
} from "@shared/api/generated";

export type {
  IntegrationConnectionData,
  IntegrationStatusRecord as IntegrationStatus,
} from "@shared/types";

/** `addIntegration`'s result: the API's answer plus the two client-side states. */
export type AddIntegrationOutcome = Omit<AddIntegrationResponse, "status"> & {
  status: AddIntegrationResponse["status"] | "redirecting" | "bearer_required";
};

/**
 * Suggested public integration from search
 */
export interface SuggestedIntegration {
  id: string;
  name: string;
  description: string;
  category: string;
  iconUrl?: string | null;
  authType?: string | null;
  relevanceScore: number;
  slug: string;
}

/**
 * Data streamed from integration_list_data tool
 */
export interface IntegrationListStreamData {
  hasSuggestions?: boolean;
  suggested?: SuggestedIntegration[];
}

/**
 * Community/Public Marketplace Types
 */

/** A marketplace card; `source` is set client-side to tell native from community. */
export type CommunityIntegration = CommunityIntegrationItem & {
  source?: "platform" | "custom";
};

export type CommunityIntegrationsResponse = CommunityListResponse;

export type PublicIntegrationResponse = PublicIntegrationDetailResponse;

/** One button in the seeded Getting-started thread's connect row. An entry
 * with an `integration_id` shows that app's icon; the last one is the
 * integrations page itself. `href` is an in-app path, opened in the same tab. */
/** How a connect starts: a bearer token for MCP servers, or the expired account to sign back in. */
export interface IntegrationConnectOptions {
  bearerToken?: string;
  accountId?: string;
}

export interface ConnectOption {
  integration_id?: string;
  label: string;
  href: string;
}

export interface ConnectOptionsData {
  options: ConnectOption[];
}
