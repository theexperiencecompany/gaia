import type { AddIntegrationResponse } from "@shared/api/generated";
import { api } from "@/lib/api/typed";
import { sanitizeRedirectUrl } from "@/lib/url-safety";

import type {
  CommunityIntegration,
  CreateCustomIntegrationRequest,
} from "../types";

/** `addIntegration`'s result: the API's answer plus the two client-side states. */
export type AddIntegrationOutcome = Omit<AddIntegrationResponse, "status"> & {
  status: AddIntegrationResponse["status"] | "redirecting" | "bearer_required";
};

export const integrationsApi = {
  /**
   * Get the configuration for all integrations from backend
   */
  getIntegrationConfig: async () => {
    try {
      return await api.get("/api/v1/integrations/config");
    } catch (error) {
      console.error("Failed to get integration config:", error);
      throw error;
    }
  },

  /**
   * Get the full catalog personalized for the user: every platform integration
   * plus the user's own custom ones, each annotated with connection status.
   * Per-tool schemas are not included — only `toolCount`. Fetch one
   * integration's tools on demand via `getIntegrationTools`.
   */
  getMyIntegrations: () => api.get("/api/v1/integrations/me"),

  /**
   * Get the full tool list for a single integration, on demand.
   */
  getIntegrationTools: (integrationId: string) =>
    api.get("/api/v1/integrations/{integration_id}/tools", {
      path: { integration_id: integrationId },
      silent: true,
    }),

  /**
   * Get the user's custom instructions for one integration.
   */
  getIntegrationInstructions: (integrationId: string) =>
    api.get(
      "/api/v1/integrations/users/me/integrations/{integration_id}/instructions",
      { path: { integration_id: integrationId }, silent: true },
    ),

  /**
   * Save the user's custom instructions for one integration.
   */
  updateIntegrationInstructions: (integrationId: string, content: string) =>
    api.put(
      "/api/v1/integrations/users/me/integrations/{integration_id}/instructions",
      {
        path: { integration_id: integrationId },
        body: { content },
        silent: true,
      },
    ),

  /**
   * Connect an integration using the unified backend endpoint.
   */
  connectIntegration: async (
    integrationId: string,
    bearerToken?: string,
  ): Promise<{ status: string; name?: string; toolsCount?: number }> => {
    if (typeof window === "undefined")
      return { status: "error", name: "Unknown" };

    const url = new URL(window.location.href);
    url.searchParams.delete("integration");
    url.searchParams.delete("oauth_success");
    url.searchParams.delete("oauth_error");
    const redirectPath = url.pathname + url.search;

    const response = await api.post(
      "/api/v1/integrations/connect/{integration_id}",
      {
        path: { integration_id: integrationId.toLowerCase() },
        body: { redirect_path: redirectPath, bearer_token: bearerToken },
      },
    );

    if (response.status === "redirect" && response.redirectUrl) {
      const safeUrl = sanitizeRedirectUrl(response.redirectUrl);
      if (!safeUrl) {
        throw new Error("Invalid redirect URL received from server");
      }
      window.location.href = safeUrl;
      return { status: "redirecting", name: response.name };
    }

    if (response.status === "error") {
      throw new Error(response.error || "Failed to connect integration");
    }

    return {
      status: response.status,
      name: response.name,
      toolsCount: response.toolsCount ?? undefined,
    };
  },

  /**
   * Disconnect an integration. The success toast is fired by the hook caller
   * (useIntegrations.disconnectIntegration) — don't double up here.
   */
  disconnectIntegration: async (integrationId: string): Promise<void> => {
    try {
      await api.delete("/api/v1/integrations/{integration_id}", {
        path: { integration_id: integrationId },
      });
    } catch (error) {
      console.error(`Failed to disconnect ${integrationId}:`, error);
      throw error;
    }
  },

  /**
   * Create a custom MCP integration.
   */
  createCustomIntegration: async (request: CreateCustomIntegrationRequest) => {
    try {
      return await api.post("/api/v1/integrations/custom", { body: request });
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
      await api.delete("/api/v1/integrations/custom/{integration_id}", {
        path: { integration_id: integrationId },
      });
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
  publishIntegration: (integrationId: string) =>
    api.post("/api/v1/integrations/custom/{integration_id}/publish", {
      path: { integration_id: integrationId },
    }),

  /**
   * Unpublish a custom integration from the marketplace
   */
  unpublishIntegration: (integrationId: string) =>
    api.post("/api/v1/integrations/custom/{integration_id}/unpublish", {
      path: { integration_id: integrationId },
    }),

  /**
   * Get community integrations for the public marketplace
   */
  getCommunityIntegrations: (params?: {
    sort?: "popular" | "recent" | "name";
    category?: string;
    limit?: number;
    offset?: number;
    search?: string;
  }) => api.get("/api/v1/integrations/community", { query: params }),

  /**
   * Get public integration details by integration ID (no auth required)
   */
  getPublicIntegration: (integrationId: string) =>
    api.get("/api/v1/integrations/public/{identifier}", {
      path: { identifier: integrationId },
    }),

  /**
   * Add a public integration to user's workspace and trigger OAuth if needed
   */
  addIntegration: async (
    integrationId: string,
    bearerToken?: string,
  ): Promise<AddIntegrationOutcome> => {
    if (typeof window === "undefined") {
      return {
        status: "error",
        integrationId,
        name: "",
        message: "Cannot add integration on server",
        redirectUrl: null,
        toolsCount: null,
        error: null,
      };
    }

    const redirectPath = `/integrations?id=${integrationId}&refresh=true`;

    const response = await api.post(
      "/api/v1/integrations/public/{integration_id}/add",
      {
        path: { integration_id: integrationId },
        body: { redirect_path: redirectPath, bearer_token: bearerToken },
      },
    );

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
   * Get native (platform) integrations for the public marketplace.
   * Fetches from the public /integrations/config endpoint and normalizes
   * to CommunityIntegration shape for card/list compatibility.
   */
  getNativeIntegrations: async (): Promise<CommunityIntegration[]> => {
    const response = await integrationsApi.getIntegrationConfig();
    return response.integrations
      .filter((i) => i.source === "platform" && i.available !== false)
      .sort((a, b) => (b.displayPriority ?? 0) - (a.displayPriority ?? 0))
      .map((i) => ({
        integrationId: i.id,
        slug: i.slug,
        name: i.name,
        description: i.description,
        category: i.category,
        // The config endpoint carries no icon or tool list; cards resolve the
        // icon by slug and the tool list is fetched per integration on demand.
        iconUrl: null,
        cloneCount: 0,
        toolCount: 0,
        tools: [],
        publishedAt: null,
        creator: null,
        source: "platform" as const,
      }));
  },

  /**
   * Get community workflows related to an integration by slug or native ID
   */
  getRelatedWorkflows: (identifier: string, limit: number = 10) =>
    api.get("/api/v1/integrations/public/{identifier}/workflows", {
      path: { identifier },
      query: { limit },
      silent: true,
    }),
};
