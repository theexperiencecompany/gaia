import { apiService } from "@/lib/api";

import type { Integration, IntegrationStatus } from "../types";

export interface IntegrationStatusResponse {
  integrations: IntegrationStatus[];
}

export interface IntegrationConfigResponse {
  integrations: Integration[];
}

export const integrationsApi = {
  /**
   * Get the configuration for all integrations from backend
   */
  getIntegrationConfig: async (): Promise<IntegrationConfigResponse> => {
    try {
      const response = (await apiService.get(
        "/integrations/config",
      )) as IntegrationConfigResponse;
      return response;
    } catch (error) {
      console.error("Failed to get integration config:", error);
      throw error;
    }
  },
  /**
   * Get the status of all integrations for the current user
   */
  getIntegrationStatus: async (): Promise<IntegrationStatusResponse> => {
    try {
      const response = (await apiService.get("/integrations/status", {
        silent: true,
      })) as {
        integrations: Array<{
          integrationId: string;
          connected: boolean;
        }>;
        debug?: {
          authorized_scopes: string[];
        };
      };

      // Map backend response to frontend format
      const integrations: IntegrationStatus[] = response.integrations.map(
        (integration) => ({
          integrationId: integration.integrationId,
          connected: integration.connected,
          lastConnected: integration.connected
            ? new Date().toISOString()
            : undefined,
        }),
      );

      return { integrations };
    } catch (error) {
      console.error("Failed to get integration status:", error);
      // Return empty array if we can't determine status
      return {
        integrations: [],
      };
    }
  },

  /**
   * Connect an integration
   * - For unauthenticated MCP: POST to backend directly, no redirect
   * - For bearer auth: pass bearerToken from modal, POST to backend directly
   * - For OAuth: redirect to loginEndpoint, backend handles OAuth flow
   */
  connectIntegration: async (
    integrationId: string,
    bearerToken?: string,
  ): Promise<{ status: string; toolsCount?: number }> => {
    // Normalize to lowercase (backend may return uppercase toolkit names)
    const normalizedId = integrationId.toLowerCase();

    // Get the integration config first
    const configResponse = await integrationsApi.getIntegrationConfig();
    const integration = configResponse.integrations.find(
      (i) => i.id.toLowerCase() === normalizedId,
    );

    if (!integration || !integration.loginEndpoint) {
      throw new Error(
        `Integration ${integrationId} is not available for connection`,
      );
    }

    // Unauthenticated MCPs are always connected - no API call needed
    if (integration.managedBy === "mcp" && integration.authType === "none") {
      return { status: "connected", toolsCount: 0 };
    }

    // For MCP integrations with bearer auth, call API directly
    if (integration.managedBy === "mcp" && integration.authType === "bearer") {
      const response = await apiService.post(`/mcp/connect/${integration.id}`, {
        bearer_token: bearerToken,
      });
      return response as { status: string; toolsCount?: number };
    }

    // If bearer token provided (from modal for non-MCP), POST to backend
    if (bearerToken) {
      const response = await apiService.post(`mcp/connect/${integration.id}`, {
        bearer_token: bearerToken,
      });
      return response as { status: string; toolsCount?: number };
    }

    if (typeof window === "undefined") return { status: "error" };

    const frontendPath = window.location.pathname + window.location.search;

    // Navigate to loginEndpoint for OAuth - backend handles redirects
    const backendUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
    const fullUrl = `${backendUrl}${integration.loginEndpoint}?redirect_path=${encodeURIComponent(frontendPath)}`;

    window.location.href = fullUrl;
    return { status: "redirecting" };
  },

  /**
   * Disconnect an integration (placeholder for future implementation)
   */
  disconnectIntegration: async (integrationId: string): Promise<void> => {
    try {
      await apiService.delete(
        `/integrations/${integrationId}`,
        {},
        {
          successMessage: "Integration disconnected successfully",
        },
      );
    } catch (error) {
      console.error(`Failed to disconnect ${integrationId}:`, error);
      throw error;
    }
  },

  /**
   * Connect an MCP integration with bearer token
   */
  connectMCPWithToken: async (
    integrationId: string,
    bearerToken: string,
  ): Promise<{ status: string; toolsCount: number }> => {
    try {
      const response = await apiService.post(`/mcp/connect/${integrationId}`, {
        bearer_token: bearerToken,
      });
      return response as { status: string; toolsCount: number };
    } catch (error) {
      console.error(`Failed to connect MCP ${integrationId}:`, error);
      throw error;
    }
  },

  /**
   * Get MCP integration status
   */
  getMCPStatus: async (): Promise<{
    integrations: Array<{
      integrationId: string;
      connected: boolean;
      status: string;
    }>;
  }> => {
    try {
      const response = await apiService.get("/mcp/status", { silent: true });
      return response as {
        integrations: Array<{
          integrationId: string;
          connected: boolean;
          status: string;
        }>;
      };
    } catch (error) {
      console.error("Failed to get MCP status:", error);
      return { integrations: [] };
    }
  },
};
