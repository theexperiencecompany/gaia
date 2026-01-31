import { apiService } from "@/lib/api";

import type {
  CommunityIntegrationsResponse,
  CreateCustomIntegrationRequest,
  CreateCustomIntegrationResponse,
  Integration,
  PublicIntegrationResponse,
  UserIntegrationsResponse,
} from "../types";

/**
 * Sanitizes a redirect URL to prevent XSS attacks.
 * Only allows http: and https: protocols.
 * Blocks dangerous schemes like javascript:, data:, vbscript:, etc.
 *
 * @param url - The URL to sanitize
 * @returns The sanitized URL if safe, null if dangerous
 */
function sanitizeRedirectUrl(url: string): string | null {
  try {
    const parsed = new URL(url);

    // Only allow http and https protocols
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      console.warn(`Blocked redirect to unsafe URL scheme: ${parsed.protocol}`);
      return null;
    }

    return url;
  } catch {
    // Invalid URL format
    console.warn(`Blocked redirect to malformed URL: ${url}`);
    return null;
  }
}

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
    bearerToken?: string,
  ): Promise<{ status: string; toolsCount?: number }> => {
    if (typeof window === "undefined") return { status: "error" };

    const redirectPath = window.location.pathname + window.location.search;

    const response = (await apiService.post(
      `/integrations/connect/${integrationId}`,
      {
        redirect_path: redirectPath,
        bearer_token: bearerToken,
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
      const safeUrl = sanitizeRedirectUrl(response.redirectUrl);
      if (!safeUrl) {
        throw new Error("Invalid redirect URL received from server");
      }
      window.location.href = safeUrl;
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
    publicUrl: string;
  }> => {
    const response = await apiService.post(
      `/integrations/custom/${integrationId}/publish`,
      {},
    );
    return response as {
      message: string;
      integrationId: string;
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
   * Get public integration details by integration ID (no auth required)
   */
  getPublicIntegration: async (
    integrationId: string,
  ): Promise<PublicIntegrationResponse> => {
    const response = await apiService.get(
      `/integrations/public/${integrationId}`,
    );
    return response as PublicIntegrationResponse;
  },

  /**
   * Add a public integration to user's workspace and trigger OAuth if needed
   */
  addIntegration: async (
    integrationId: string,
    bearerToken?: string,
  ): Promise<{
    status:
      | "connected"
      | "redirect"
      | "redirecting"
      | "bearer_required"
      | "error";
    integrationId: string;
    name: string;
    message: string;
    toolsCount?: number;
    redirectUrl?: string;
    error?: string;
  }> => {
    if (typeof window === "undefined") {
      return {
        status: "error",
        integrationId,
        name: "",
        message: "Cannot add integration on server",
      };
    }

    const redirectPath = `/integrations?id=${integrationId}&refresh=true`;

    const response = (await apiService.post(
      `/integrations/public/${integrationId}/add`,
      {
        redirect_path: redirectPath,
        bearer_token: bearerToken,
      },
    )) as {
      status: "connected" | "redirect" | "error";
      integrationId: string;
      name: string;
      message: string;
      toolsCount?: number;
      redirectUrl?: string;
      error?: string;
    };

    if (response.status === "redirect" && response.redirectUrl) {
      const safeUrl = sanitizeRedirectUrl(response.redirectUrl);
      if (!safeUrl) {
        throw new Error("Invalid redirect URL received from server");
      }
      window.location.href = safeUrl;
      return { ...response, status: "redirecting" };
    }

    // Return bearer_required as a special status instead of throwing
    if (response.status === "error" && response.error === "bearer_required") {
      return { ...response, status: "bearer_required" };
    }

    if (response.status === "error") {
      throw new Error(response.error || "Failed to add integration");
    }

    return response;
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
