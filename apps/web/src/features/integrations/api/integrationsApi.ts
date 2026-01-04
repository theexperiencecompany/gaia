import { apiService } from "@/lib/api";

import type {
  CreateCustomIntegrationRequest,
  Integration,
  IntegrationStatus,
  MarketplaceIntegration,
  MarketplaceResponse,
  UserIntegrationsResponse,
} from "../types";

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
   * - For unauthenticated MCP: POST to backend to create user_integrations record
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

    // For MCP integrations with no auth, call API to create user_integrations record
    if (integration.managedBy === "mcp" && integration.authType === "none") {
      const response = await apiService.post(
        `/mcp/connect/${integration.id}`,
        {},
      );
      return response as { status: string; toolsCount?: number };
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
      // Get the integration config to check if it's MCP
      const configResponse = await integrationsApi.getIntegrationConfig();
      const integration = configResponse.integrations.find(
        (i) => i.id.toLowerCase() === integrationId.toLowerCase(),
      );

      // MCP integrations use the /mcp endpoint
      if (integration?.managedBy === "mcp") {
        await apiService.delete(
          `/mcp/${integrationId}`,
          {},
          {
            successMessage: "Integration disconnected successfully",
          },
        );
      } else {
        await apiService.delete(
          `/integrations/${integrationId}`,
          {},
          {
            successMessage: "Integration disconnected successfully",
          },
        );
      }
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

  // Marketplace API Methods

  /**
   * Get all available integrations from the marketplace
   */
  getMarketplace: async (category?: string): Promise<MarketplaceResponse> => {
    try {
      const params = category
        ? `?category=${encodeURIComponent(category)}`
        : "";
      const response = await apiService.get(
        `/integrations/marketplace${params}`,
      );
      return response as MarketplaceResponse;
    } catch (error) {
      console.error("Failed to get marketplace:", error);
      return { featured: [], integrations: [], total: 0 };
    }
  },

  /**
   * Get a single integration from the marketplace
   */
  getMarketplaceIntegration: async (
    integrationId: string,
  ): Promise<MarketplaceIntegration | null> => {
    try {
      const response = await apiService.get(
        `/integrations/marketplace/${integrationId}`,
      );
      return response as MarketplaceIntegration;
    } catch (error) {
      console.error(`Failed to get integration ${integrationId}:`, error);
      return null;
    }
  },

  /**
   * Get user's added integrations
   */
  getUserIntegrations: async (): Promise<UserIntegrationsResponse> => {
    try {
      const response = await apiService.get(
        "/integrations/users/me/integrations",
      );
      return response as UserIntegrationsResponse;
    } catch (error) {
      console.error("Failed to get user integrations:", error);
      return { integrations: [], total: 0 };
    }
  },

  /**
   * Add an integration to user's workspace
   */
  addToWorkspace: async (
    integrationId: string,
  ): Promise<{
    status: string;
    integration_id: string;
    connection_status: string;
  }> => {
    try {
      const response = await apiService.post(
        "/integrations/users/me/integrations",
        {
          integration_id: integrationId,
        },
      );
      return response as {
        status: string;
        integration_id: string;
        connection_status: string;
      };
    } catch (error) {
      console.error(`Failed to add integration ${integrationId}:`, error);
      throw error;
    }
  },

  /**
   * Remove an integration from user's workspace
   */
  removeFromWorkspace: async (integrationId: string): Promise<void> => {
    try {
      await apiService.delete(
        `/integrations/users/me/integrations/${integrationId}`,
      );
    } catch (error) {
      console.error(`Failed to remove integration ${integrationId}:`, error);
      throw error;
    }
  },

  /**
   * Create a custom MCP integration
   */
  createCustomIntegration: async (
    request: CreateCustomIntegrationRequest,
  ): Promise<{ integration_id: string; name: string }> => {
    try {
      const response = await apiService.post("/integrations/custom", request);
      return response as { integration_id: string; name: string };
    } catch (error) {
      console.error("Failed to create custom integration:", error);
      throw error;
    }
  },

  /**
   * Delete a custom integration
   */
  deleteCustomIntegration: async (integrationId: string): Promise<void> => {
    try {
      await apiService.delete(`/integrations/custom/${integrationId}`);
    } catch (error) {
      console.error(
        `Failed to delete custom integration ${integrationId}:`,
        error,
      );
      throw error;
    }
  },
};
