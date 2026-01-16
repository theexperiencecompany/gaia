import { apiService } from "@/lib/api";

import type {
  CommunityIntegrationsResponse,
  CreateCustomIntegrationRequest,
  CreateCustomIntegrationResponse,
  Integration,
  PublicIntegrationResponse,
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
   * Get integration status (connected/disconnected) for all platform integrations
   */
  getIntegrationStatus: async (): Promise<IntegrationStatusResponse> => {
    try {
      const response = await apiService.get("/integrations/status");
      return response as IntegrationStatusResponse;
    } catch (error) {
      console.error("Failed to get integration status:", error);
      return { integrations: [] };
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
      integrationId: string;
      message?: string;
      toolsCount?: number;
      redirectUrl?: string;
      error?: string;
    };

    if (response.status === "redirect" && response.redirectUrl) {
      window.location.href = response.redirectUrl;
      return { status: "redirecting" };
    }

    if (response.status === "error") {
      throw new Error(response.error || "Failed to connect integration");
    }

    return {
      status: response.status,
      toolsCount: response.toolsCount ?? undefined,
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

  /**
   * Publish a custom integration to the community marketplace
   */
  publishIntegration: async (
    integrationId: string,
  ): Promise<{
    message: string;
    integrationId: string;
    slug: string;
    publicUrl: string;
  }> => {
    const response = await apiService.post(
      `/integrations/custom/${integrationId}/publish`,
      {},
    );
    return response as {
      message: string;
      integrationId: string;
      slug: string;
      publicUrl: string;
    };
  },

  /**
   * Unpublish a custom integration from the marketplace
   */
  unpublishIntegration: async (
    integrationId: string,
  ): Promise<{
    message: string;
    integrationId: string;
  }> => {
    const response = await apiService.post(
      `/integrations/custom/${integrationId}/unpublish`,
      {},
    );
    return response as {
      message: string;
      integrationId: string;
    };
  },

  /**
   * Get community integrations for the public marketplace
   */
  getCommunityIntegrations: async (params?: {
    sort?: "popular" | "recent" | "name";
    category?: string;
    limit?: number;
    offset?: number;
    search?: string;
  }): Promise<CommunityIntegrationsResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.sort) searchParams.set("sort", params.sort);
    if (params?.category) searchParams.set("category", params.category);
    if (params?.limit) searchParams.set("limit", params.limit.toString());
    if (params?.offset) searchParams.set("offset", params.offset.toString());
    if (params?.search) searchParams.set("search", params.search);

    const query = searchParams.toString();
    const response = await apiService.get(
      `/integrations/community${query ? `?${query}` : ""}`,
    );
    return response as CommunityIntegrationsResponse;
  },

  /**
   * Get public integration details by slug (no auth required)
   */
  getPublicIntegration: async (
    slug: string,
  ): Promise<PublicIntegrationResponse> => {
    const response = await apiService.get(`/integrations/public/${slug}`);
    return response as PublicIntegrationResponse;
  },

  /**
   * Clone a public integration to user's workspace
   */
  cloneIntegration: async (
    slug: string,
  ): Promise<{
    message: string;
    integrationId: string;
    name: string;
    connectionStatus: string;
  }> => {
    const response = await apiService.post(
      `/integrations/public/${slug}/clone`,
      {},
    );
    return response as {
      message: string;
      integrationId: string;
      name: string;
      connectionStatus: string;
    };
  },

  /**
   * Search public integrations using semantic search
   */
  searchIntegrations: async (
    query: string,
  ): Promise<{
    integrations: PublicIntegrationResponse[];
    query: string;
  }> => {
    const response = await apiService.get(
      `/integrations/search?q=${encodeURIComponent(query)}`,
    );
    return response as {
      integrations: PublicIntegrationResponse[];
      query: string;
    };
  },
};
