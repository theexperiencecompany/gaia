/**
 * Integration system types and interfaces.
 *
 * The personalized-catalog and per-integration-tools shapes are backend-driven
 * and shared with mobile — they live in `@shared/types` (the canonical source
 * mirroring the API models). Re-exported here so feature code keeps importing
 * from `../types`.
 */

import type { IntegrationManagedBy } from "@shared/types";

export type {
  IntegrationConnectionData,
  IntegrationManagedBy,
  IntegrationStatusRecord as IntegrationStatus,
  IntegrationToolsResponse,
  MyIntegrationsResponse,
} from "@shared/types";

/**
 * Integration category values - synced with backend INTEGRATION_CATEGORIES
 * (apps/api/app/services/integrations/category_inference_service.py)
 */
export type IntegrationCategoryValue =
  | "productivity"
  | "communication"
  | "developer"
  | "analytics"
  | "finance"
  | "ai-ml"
  | "education"
  | "personal"
  | "capabilities"
  | "other";

export interface IntegrationInstructions {
  integrationId: string;
  content: string;
  updatedBy: "user" | "agent";
  updatedAt: string | null;
}

export interface Integration {
  id: string;
  name: string;
  description: string;
  category: IntegrationCategoryValue;
  status: "connected" | "not_connected" | "created" | "expired" | "error";
  /** ISO timestamp of when the upstream grant died. Only set when `status` is `expired`. */
  expiredAt?: string;
  displayPriority?: number;
  isFeatured?: boolean;
  managedBy?: IntegrationManagedBy;
  available?: boolean;
  authType?: "oauth" | "bearer" | "none";
  source?: "platform" | "custom";
  requiresAuth?: boolean;
  isPublic?: boolean;
  createdBy?: string;
  tools?: Array<{ name: string; description?: string }>;
  toolCount?: number;
  iconUrl?: string;
  creator?: {
    name: string | null;
    picture: string | null;
  } | null;
  slug: string;
}

/**
 * Where a `managedBy: "cli"` connection currently stands.
 *
 * `installing` and `awaiting_approval` are waiting states the client polls
 * through; `needs_token` hands control back to the user; `connected` and
 * `failed` are terminal.
 */
export type CliConnectPhase =
  | "installing"
  | "needs_token"
  | "awaiting_approval"
  | "connected"
  | "failed";

/**
 * What the user has to see and do right now for a CLI connection.
 *
 * `instructions` is the tool's own output relayed verbatim — the approval text
 * (carrying a URL and a code) while waiting, or the failure detail when the
 * phase is `failed`. GAIA never parses or rewords it.
 */
export interface CliConnectDetail {
  phase: CliConnectPhase;
  instructions?: string | null;
  /** Prompt copy for the paste-a-token step, e.g. "Personal access token". */
  tokenLabel?: string | null;
  /** Where the user can go to mint that token. */
  tokenHelpUrl?: string | null;
}

/**
 * The unified connect endpoint's response.
 *
 * `pending` is the CLI transport's steady state: the endpoint is idempotent
 * and advances the connection one step per call, so the client re-POSTs it
 * until the status leaves `pending`, reading `cli` for what to show meanwhile.
 */
export interface ConnectIntegrationResponse {
  status: "connected" | "redirect" | "error" | "pending";
  integrationId: string;
  name: string;
  message?: string | null;
  toolsCount?: number | null;
  redirectUrl?: string | null;
  error?: string | null;
  cli?: CliConnectDetail | null;
}

export interface CreateCustomIntegrationRequest {
  name: string;
  description?: string;
  category?: string;
  server_url: string;
  requires_auth?: boolean;
  auth_type?: "none" | "oauth" | "bearer";
  is_public?: boolean;
  bearer_token?: string;
}

/**
 * Result of connection testing after creating a custom integration
 * Matches backend CustomIntegrationConnectionResult
 */
export interface ConnectionTestResult {
  status: "connected" | "requires_oauth" | "failed" | "created";
  toolsCount?: number;
  oauthUrl?: string;
  error?: string;
}

/**
 * Response from create custom integration endpoint
 * Matches backend CreateCustomIntegrationResponse
 */
export interface CreateCustomIntegrationResponse {
  status: string;
  message: string;
  integrationId: string;
  name: string;
  connection?: ConnectionTestResult;
}

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

export interface IntegrationHowItWorksStep {
  title: string;
  body: string;
}

export interface IntegrationFAQ {
  question: string;
  answer: string;
}

export interface IntegrationContent {
  useCases: string[];
  howItWorks: IntegrationHowItWorksStep[];
  faqs: IntegrationFAQ[];
}

export interface CommunityIntegrationCreator {
  name: string | null;
  picture: string | null;
}

export interface CommunityIntegration {
  integrationId: string;
  slug: string;
  name: string;
  description: string;
  category: string;
  iconUrl: string | null;
  cloneCount: number;
  toolCount: number;
  tools: Array<{ name: string; description: string | null }>;
  publishedAt: string | null;
  creator: CommunityIntegrationCreator | null;
  source?: "platform" | "custom";
}

export interface CommunityIntegrationsResponse {
  integrations: CommunityIntegration[];
  total: number;
  hasMore: boolean;
}

export interface PublicIntegrationResponse extends CommunityIntegration {
  mcpConfig?: {
    serverUrl: string;
    requiresAuth: boolean;
    authType: string | null;
  } | null;
  source?: "platform" | "custom";
  authType?: "oauth" | "bearer" | "none" | null;
  content?: IntegrationContent | null;
}
