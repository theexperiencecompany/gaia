/**
 * Shared integrations API contract.
 * Defines endpoint constants and parameter interfaces used by all platforms.
 * Each platform implements the actual HTTP calls using its own HTTP client.
 */

export const INTEGRATION_ENDPOINTS = {
  config: "/integrations/config",
  status: "/integrations/status",
  userIntegrations: "/integrations/users/me/integrations",
  addToWorkspace: "/integrations/users/me/integrations",
  removeFromWorkspace: (integrationId: string) =>
    `/integrations/users/me/integrations/${integrationId}`,
  connect: (integrationId: string) =>
    `/integrations/connect/${integrationId.toLowerCase()}`,
  disconnect: (integrationId: string) => `/integrations/${integrationId}`,
  custom: "/integrations/custom",
  customIntegration: (integrationId: string) =>
    `/integrations/custom/${integrationId}`,
  publishCustom: (integrationId: string) =>
    `/integrations/custom/${integrationId}/publish`,
  unpublishCustom: (integrationId: string) =>
    `/integrations/custom/${integrationId}/unpublish`,
  community: "/integrations/community",
  public: (integrationId: string) => `/integrations/public/${integrationId}`,
  addPublic: (integrationId: string) =>
    `/integrations/public/${integrationId}/add`,
  search: "/integrations/search",
  mcpTest: (integrationId: string) => `/mcp/test/${integrationId}`,
} as const;

export interface ConnectIntegrationParams {
  redirect_path?: string;
  bearer_token?: string;
}

export interface AddPublicIntegrationParams {
  redirect_path?: string;
  bearer_token?: string;
}

export interface AddToWorkspaceParams {
  integration_id: string;
}

export interface CommunityIntegrationsParams {
  sort?: "popular" | "recent" | "name";
  category?: string;
  limit?: number;
  offset?: number;
  search?: string;
}

export interface SearchIntegrationsParams {
  q: string;
}

export interface CreateCustomIntegrationParams {
  name: string;
  description?: string;
  category?: string;
  server_url: string;
  requires_auth?: boolean;
  auth_type?: "none" | "oauth" | "bearer";
  is_public?: boolean;
  bearer_token?: string;
}

export interface IntegrationConnectResponse {
  status: "connected" | "redirect" | "error";
  integrationId: string;
  name: string;
  message?: string;
  toolsCount?: number;
  redirectUrl?: string;
  error?: string;
}

export interface IntegrationAddPublicResponse {
  status: "connected" | "redirect" | "bearer_required" | "error";
  integrationId: string;
  name: string;
  message: string;
  toolsCount?: number;
  redirectUrl?: string;
  error?: string;
}

export interface IntegrationStatusEntry {
  integrationId: string;
  connected: boolean;
}

export interface IntegrationStatusResponse {
  integrations: IntegrationStatusEntry[];
}

export interface IntegrationPublishResponse {
  message: string;
  integrationId: string;
  publicUrl: string;
}

export interface IntegrationUnpublishResponse {
  message: string;
  integrationId: string;
}

export interface IntegrationWorkspaceAddResponse {
  status: string;
  integration_id: string;
  connection_status: string;
}

export interface McpTestConnectionResponse {
  status: "connected" | "requires_oauth" | "failed";
  tools_count?: number;
  oauth_url?: string;
  error?: string;
}

export interface IntegrationListParams {
  category?: string;
  search?: string;
  limit?: number;
  offset?: number;
  featured?: boolean;
}

export interface ConnectParams {
  integrationId: string;
  redirectPath?: string;
  bearerToken?: string;
}

export interface DisconnectParams {
  integrationId: string;
}

export interface TestConnectionParams {
  integrationId: string;
}

type IntegrationEndpointValue = string | ((id: string) => string);

/**
 * Resolve an INTEGRATION_ENDPOINTS value to a URL string.
 * For string endpoints, returns the value directly.
 * For function endpoints, calls it with the provided id.
 */
export function buildIntegrationUrl(
  endpoint: IntegrationEndpointValue,
  id?: string,
): string {
  if (typeof endpoint === "function") {
    if (!id) {
      throw new Error(
        "buildIntegrationUrl: id is required for parameterised endpoints",
      );
    }
    return endpoint(id);
  }
  return endpoint;
}
