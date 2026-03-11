/**
 * Integration category values - synced with backend and web
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
  slug: string;
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
