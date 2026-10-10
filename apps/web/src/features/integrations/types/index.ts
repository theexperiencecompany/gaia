/**
 * Integration system types and interfaces.
 *
 * The personalized-catalog and per-integration-tools shapes are backend-driven
 * and shared with mobile — they live in `@shared/types` (the canonical source
 * mirroring the API models). Re-exported here so feature code keeps importing
 * from `../types`.
 */

import type {
  CommunityIntegrationItem,
  CommunityListResponse,
  IntegrationContent,
  IntegrationInstructionsResponse,
} from "@shared/api/generated";

export type {
  CreateCustomIntegrationRequest,
  CreateCustomIntegrationResponse,
  IntegrationContent,
} from "@shared/api/generated";

export type {
  IntegrationConnectionData,
  IntegrationStatusRecord as IntegrationStatus,
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

export type IntegrationInstructions = IntegrationInstructionsResponse;

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
  managedBy?: "self" | "composio" | "mcp" | "internal";
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
 * Response from create custom integration endpoint
 * Matches backend CreateCustomIntegrationResponse
 */

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

/** One button in the seeded Getting-started thread's connect row. An entry
 * with an `integration_id` shows that app's icon; the last one is the
 * integrations page itself. `href` is an in-app path, opened in the same tab. */
export interface ConnectOption {
  integration_id?: string;
  label: string;
  href: string;
}

export interface ConnectOptionsData {
  options: ConnectOption[];
}
