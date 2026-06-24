/**
 * Integration system types and interfaces
 * Shared between web and mobile applications.
 * Synced with backend integration models.
 */

/**
 * Integration category values - synced with backend INTEGRATION_CATEGORIES
 * (apps/api/app/services/integrations/category_inference_service.py)
 */
export type IntegrationCategory =
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

export type IntegrationStatusValue = "connected" | "not_connected" | "created";

export type IntegrationAuthType = "oauth" | "bearer" | "none";

export type IntegrationManagedBy = "composio" | "mcp" | "internal" | "self";

export interface IntegrationTool {
  name: string;
  description?: string | null;
}

export interface IntegrationCreator {
  name: string | null;
  picture: string | null;
}

export interface Integration {
  id: string;
  name: string;
  description: string;
  category: IntegrationCategory;
  status: IntegrationStatusValue;
  slug: string;
  isSpecial?: boolean;
  displayPriority?: number;
  includedIntegrations?: string[];
  isFeatured?: boolean;
  managedBy?: IntegrationManagedBy;
  available?: boolean;
  authType?: IntegrationAuthType;
  source?: "platform" | "custom";
  requiresAuth?: boolean;
  isPublic?: boolean;
  createdBy?: string;
  tools?: IntegrationTool[];
  iconUrl?: string;
  creator?: IntegrationCreator | null;
}

/**
 * Represents the connection status record for a user's integration.
 * Note: status is restricted to "created" | "connected" because this represents
 * the database record state. The broader Integration.status ("not_connected" | "error")
 * is derived at the API layer based on whether a UserIntegration record exists.
 */
export interface UserIntegration {
  integrationId: string;
  status: "created" | "connected";
  createdAt: string;
  connectedAt?: string;
  integration: MarketplaceIntegration;
}

/**
 * Marketplace API type - matches backend IntegrationResponse with camelCase aliases
 */
export interface MarketplaceIntegration {
  integrationId: string;
  name: string;
  description: string;
  category: string;
  managedBy: IntegrationManagedBy;
  source: "platform" | "custom";
  isFeatured: boolean;
  displayPriority: number;
  requiresAuth: boolean;
  authType?: IntegrationAuthType;
  tools?: IntegrationTool[];
  iconUrl?: string;
  isPublic?: boolean;
  createdBy?: string;
  publishedAt?: string;
  cloneCount?: number;
  slug: string;
  creator?: IntegrationCreator | null;
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
  creator: IntegrationCreator | null;
  source?: "platform" | "custom";
}

/**
 * Per-user connection status for one integration, derived from the personalized
 * catalog. Consumed by web's `useIntegrations.getIntegrationStatus`.
 */
export interface IntegrationStatusRecord {
  integrationId: string;
  connected: boolean;
  lastConnected?: string;
  error?: string;
  metadata?: Record<string, unknown>;
}

/**
 * One integration as it pertains to the current user: catalog metadata plus
 * their connection `status`, without the heavy per-tool schemas (only
 * `toolCount`). Backed by `GET /integrations/me`; mirrors the backend
 * `MyIntegrationItem`. Fetch full tools on demand from
 * `GET /integrations/{id}/tools` (`IntegrationToolsResponse`).
 */
export interface MyIntegrationItem {
  id: string;
  name: string;
  description: string;
  category: string;
  source: "platform" | "custom";
  managedBy: IntegrationManagedBy;
  status: "connected" | "created" | "not_connected";
  requiresAuth: boolean;
  authType?: IntegrationAuthType | null;
  isFeatured: boolean;
  displayPriority: number;
  available: boolean;
  iconUrl?: string | null;
  slug?: string | null;
  toolCount: number;
  isPublic?: boolean | null;
  createdBy?: string | null;
  publishedAt?: string | null;
  cloneCount: number;
  creator?: IntegrationCreator | null;
}

/**
 * The full integration catalog personalized for one user (platform + their own
 * custom integrations), each carrying connection status. Replaces the
 * client-side merge of /config + /status + /users/me/integrations.
 */
export interface MyIntegrationsResponse {
  integrations: MyIntegrationItem[];
  total: number;
}

/**
 * Full tool list for a single integration, fetched on demand from
 * `GET /integrations/{id}/tools`. Mirrors the backend `IntegrationToolsResponse`.
 */
export interface IntegrationToolsResponse {
  integrationId: string;
  tools: IntegrationTool[];
  count: number;
}

export interface CommunityIntegrationsResponse {
  integrations: CommunityIntegration[];
  total: number;
  hasMore: boolean;
}

export interface CommunitySearchParams {
  search?: string;
  category?: string;
  limit?: number;
  offset?: number;
  sort?: "popular" | "recent" | "name";
}

export interface PublicIntegrationResponse extends CommunityIntegration {
  mcpConfig?: {
    serverUrl: string;
    requiresAuth: boolean;
    authType: string | null;
  } | null;
  authType?: IntegrationAuthType | null;
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
