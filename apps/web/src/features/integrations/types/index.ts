/**
 * Integration system types and interfaces
 */

export interface Integration {
  id: string;
  name: string;
  description: string;
  category:
    | "productivity"
    | "communication"
    | "developer"
    | "social"
    | "business"
    | "custom";
  status: "connected" | "not_connected" | "created" | "error";
  // New properties for unified integrations
  isSpecial?: boolean;
  displayPriority?: number;
  includedIntegrations?: string[];
  isFeatured?: boolean;
  managedBy?: "self" | "composio" | "mcp" | "internal";
  available?: boolean;
  authType?: "oauth" | "bearer" | "none";
  // Marketplace properties
  source?: "platform" | "custom";
  requiresAuth?: boolean;
  isPublic?: boolean;
  createdBy?: string;
  tools?: Array<{ name: string; description?: string }>;
  // Custom integration icon (favicon from MCP server)
  iconUrl?: string;
}

export interface IntegrationStatus {
  integrationId: string;
  connected: boolean;
  lastConnected?: string;
  error?: string;
  metadata?: Record<string, unknown>;
}

export interface IntegrationCategory {
  id: string;
  name: string;
  description: string;
  integrations: Integration[];
}

export type IntegrationAction =
  | "connect"
  | "disconnect"
  | "settings"
  | "refresh";

export interface IntegrationActionEvent {
  integration: Integration;
  action: IntegrationAction;
}

// Marketplace API Types - matches backend IntegrationResponse with camelCase aliases
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
}

// Matches backend UserIntegrationResponse with camelCase aliases
// Note: status is restricted to "created" | "connected" because this represents
// the database record state. The broader Integration.status ("not_connected" | "error")
// is derived at the API layer based on whether a UserIntegration record exists.
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

export interface CreateCustomIntegrationRequest {
  name: string;
  description?: string;
  category?: string;
  server_url: string;
  requires_auth?: boolean;
  auth_type?: "none" | "oauth" | "bearer";
  is_public?: boolean;
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
 * Integration connection types for chat messages
 * (Merged from types/features/integrationTypes.ts)
 */
export interface IntegrationConnectionData {
  integration_id: string;
  message: string;
}

export interface IntegrationInfo {
  id: string;
  name: string;
  description: string;
  category: string;
  connected: boolean;
}

export interface IntegrationListData {
  integrations: IntegrationInfo[];
  total_count: number;
  connected_count: number;
}
