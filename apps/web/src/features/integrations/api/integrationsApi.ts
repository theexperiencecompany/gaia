import { apiService } from "@/lib/api";

import type {
  ConnectionTestResult,
  CreateCustomIntegrationRequest,
  CreateCustomIntegrationResponse,
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
   * Connect an integration using the unified backend endpoint.
   *
   * The backend handles all integration types (MCP, Composio, Google, custom)
   * and returns one of:
   * - connected: Integration is ready to use
   * - redirect: OAuth required, frontend should redirect to redirect_url
   * - error: Connection failed
   */
  connectIntegration: async (
    integrationId: string,
  ): Promise<{ status: string; toolsCount?: number }> => {
    if (typeof window === "undefined") return { status: "error" };

    const redirectPath = window.location.pathname + window.location.search;

    const response = (await apiService.post(
      `/integrations/connect/${integrationId}`,
      {
        redirect_path: redirectPath,
      },
    )) as {
      status: "connected" | "redirect" | "error";
      integration_id: string;
      message?: string;
      tools_count?: number;
      redirect_url?: string;
      error?: string;
    };

    if (response.status === "redirect" && response.redirect_url) {
      window.location.href = response.redirect_url;
      return { status: "redirecting" };
    }

    if (response.status === "error") {
      throw new Error(response.error || "Failed to connect integration");
    }

    return {
      status: response.status,
      toolsCount: response.tools_count,
    };
  },

  /**
   * Disconnect an integration.
   * The backend handles all integration types uniformly.
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
   * Create a custom MCP integration.
   * Returns connection result with auto-connection status.
   */
  createCustomIntegration: async (
    request: CreateCustomIntegrationRequest,
  ): Promise<CreateCustomIntegrationResponse> => {
    try {
      const response = await apiService.post("/integrations/custom", request);
      return response as CreateCustomIntegrationResponse;
    } catch (error) {
      console.error("Failed to create custom integration:", error);
      throw error;
    }
  },

  /**
   * Test connection to an MCP server.
   * Can be used to retry failed connections.
   */
  testConnection: async (
    integrationId: string,
  ): Promise<ConnectionTestResult> => {
    try {
      const response = await apiService.post(`/mcp/test/${integrationId}`, {});
      return response as ConnectionTestResult;
    } catch (error) {
      console.error(`Failed to test connection ${integrationId}:`, error);
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
