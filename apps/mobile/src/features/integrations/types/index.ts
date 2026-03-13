/**
 * Integration category values - synced with backend and web
 */
export type IntegrationCategoryValue =
  | "productivity"
  | "communication"
  | "social"
  | "developer"
  | "analytics"
  | "finance"
  | "ai-ml"
  | "education"
  | "personal"
  | "capabilities"
  | "other";

export interface Integration {
  id: string;
  name: string;
  description: string;
  category: IntegrationCategoryValue;
  status: "connected" | "not_connected" | "created" | "error";
  isSpecial?: boolean;
  displayPriority?: number;
  includedIntegrations?: string[];
  isFeatured?: boolean;
  managedBy?: "self" | "composio" | "mcp" | "internal";
  available?: boolean;
  authType?: "oauth" | "bearer" | "none";
  source?: "platform" | "custom";
  requiresAuth?: boolean;
  isPublic?: boolean;
  createdBy?: string;
  tools?: Array<{ name: string; description?: string }>;
  iconUrl?: string;
  slug: string;
  creator?: {
    name: string | null;
    picture: string | null;
  } | null;
}

export interface IntegrationStatus {
  integrationId: string;
  connected: boolean;
}

export interface IntegrationsConfigResponse {
  integrations: Array<{
    id: string;
    name: string;
    description: string;
    category: string;
    provider?: string;
    available?: boolean;
    loginEndpoint?: string;
    isSpecial?: boolean;
    displayPriority?: number;
    includedIntegrations?: string[];
    isFeatured?: boolean;
    managedBy?: string;
    source?: string;
    authType?: string;
    iconUrl?: string;
    slug?: string;
  }>;
}

export interface IntegrationsStatusResponse {
  integrations: IntegrationStatus[];
}

export interface MarketplaceIntegration {
  integrationId: string;
  name: string;
  description: string;
  category: string;
  managedBy: "self" | "composio" | "mcp" | "internal";
  source: "platform" | "custom";
  isFeatured: boolean;
  displayPriority: number;
  requiresAuth: boolean;
  authType?: "oauth" | "bearer" | "none";
  tools?: Array<{ name: string; description?: string }>;
  iconUrl?: string;
  isPublic?: boolean;
  createdBy?: string;
  publishedAt?: string;
  cloneCount?: number;
  slug: string;
  creator?: {
    name: string | null;
    picture: string | null;
  } | null;
}

export interface UserIntegration {
  integrationId: string;
  status: "created" | "connected";
  createdAt: string;
  connectedAt?: string;
  integration: MarketplaceIntegration;
}

export interface UserIntegrationsResponse {
  integrations: UserIntegration[];
  total: number;
}

/**
 * Legacy type kept for backward compat with connect-drawer
 */
export interface IntegrationWithStatus extends Integration {
  connected: boolean;
  logo: string;
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
  publishedAt: string;
  creator: CommunityIntegrationCreator | null;
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
  };
}

export interface CommunitySearchParams {
  search?: string;
  category?: string;
  limit?: number;
  offset?: number;
  sort?: "popular" | "recent" | "name";
}
