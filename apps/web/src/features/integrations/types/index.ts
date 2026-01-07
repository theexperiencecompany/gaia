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

// Marketplace API Types
export interface MarketplaceIntegration {
  integration_id: string;
  name: string;
  description: string;
  category: string;
  managed_by: "self" | "composio" | "mcp" | "internal";
  source: "platform" | "custom";
  is_featured: boolean;
  display_priority: number;
  requires_auth: boolean;
  auth_type?: "oauth" | "bearer" | "none";
  tools?: Array<{ name: string; description?: string }>;
  icon_url?: string;
  is_public?: boolean;
  created_by?: string;
}

export interface MarketplaceResponse {
  featured: MarketplaceIntegration[];
  integrations: MarketplaceIntegration[];
  total: number;
}

export interface UserIntegration {
  integration_id: string;
  status: "created" | "connected";
  created_at: string;
  connected_at?: string;
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
 */
export interface ConnectionTestResult {
  status: "connected" | "requires_oauth" | "failed" | "created";
  tools_count?: number;
  oauth_url?: string;
  error?: string;
}

/**
 * Response from create custom integration endpoint
 * Includes automatic connection test result
 */
export interface CreateCustomIntegrationResponse {
  status: string;
  message: string;
  integration_id: string;
  name: string;
  connection?: ConnectionTestResult;
}
