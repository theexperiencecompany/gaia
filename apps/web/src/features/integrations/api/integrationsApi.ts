import { apiService } from "@/lib/api";

import type {
  CreateCustomIntegrationRequest,
  CreateCustomIntegrationResponse,
  Integration,
  UserIntegrationsResponse,
} from "../types";

export interface IntegrationStatusResponse {
  integrations: Array<{
    integrationId: string;
    connected: boolean;
  }>;
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
   * Get user's integrations with status
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
   * Connect an integration using the unified backend endpoint.
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
   */
  testConnection: async (
    integrationId: string,
  ): Promise<{
    status: "connected" | "requires_oauth" | "failed";
    tools_count?: number;
    oauth_url?: string;
    error?: string;
  }> => {
    try {
      const response = await apiService.post(`/mcp/test/${integrationId}`, {});
      return response as {
        status: "connected" | "requires_oauth" | "failed";
        tools_count?: number;
        oauth_url?: string;
        error?: string;
      };
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
