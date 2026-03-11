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

export type IntegrationStatusValue =
  | "connected"
  | "not_connected"
  | "created"
  | "error";

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
  publishedAt: string;
  creator: IntegrationCreator | null;
}
