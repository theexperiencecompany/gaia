/**
 * Integration types the API does not describe: client-side states and stream
 * frames. A catalog entry is the generated `MyIntegrationItem`.
 */

import type {
  AddIntegrationResponse,
  CommunityIntegrationItem,
  CommunityListResponse,
  ConnectIntegrationResponse,
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

/** `connectIntegration`'s result: the API's answer plus the client-side redirect. */
export type ConnectIntegrationOutcome = Omit<
  ConnectIntegrationResponse,
  "status"
> & {
  status: ConnectIntegrationResponse["status"] | "redirecting";
};

/**
 * Community/Public Marketplace Types
 */

/** A marketplace card; `source` is set client-side to tell native from community. */
export type CommunityIntegration = CommunityIntegrationItem & {
  source?: "platform" | "custom";
};

export type CommunityIntegrationsResponse = CommunityListResponse;

export type PublicIntegrationResponse = PublicIntegrationDetailResponse;

/** How a connect starts: a bearer token for MCP servers, or the expired account to sign back in. */
export interface IntegrationConnectOptions {
  bearerToken?: string;
  accountId?: string;
}
