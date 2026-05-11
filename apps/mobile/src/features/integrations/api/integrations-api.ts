import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { apiService } from "@/lib/api";
import { API_ORIGIN } from "@/lib/constants";
import type {
  CommunityIntegrationsResponse,
  CommunitySearchParams,
  Integration,
  IntegrationCategoryValue,
  IntegrationsConfigResponse,
  IntegrationsStatusResponse,
  PublicIntegrationResponse,
  UserIntegrationsResponse,
} from "../types";

WebBrowser.maybeCompleteAuthSession();

/**
 * Fetch all integrations merged with their status.
 * Uses the same endpoints as web: /integrations/config, /integrations/status,
 * and /integrations/users/me/integrations
 */
export async function fetchIntegrations(): Promise<Integration[]> {
  try {
    const [configResponse, statusResponse, userResponse] = await Promise.all([
      apiService.get<IntegrationsConfigResponse>("/integrations/config"),
      apiService
        .get<IntegrationsStatusResponse>("/integrations/status")
        .catch(() => ({ integrations: [] }) as IntegrationsStatusResponse),
      apiService
        .get<UserIntegrationsResponse>("/integrations/users/me/integrations")
        .catch(
          () => ({ integrations: [], total: 0 }) as UserIntegrationsResponse,
        ),
    ]);

    const statuses = statusResponse.integrations;
    const userIntegrations = userResponse.integrations;

    // Build user integrations list (includes custom integrations)
    const userIntegrationsList: Integration[] = userIntegrations.map((ui) => ({
      id: ui.integrationId,
      name: ui.integration.name,
      description: ui.integration.description,
      category: ui.integration.category as IntegrationCategoryValue,
      status: ui.status as Integration["status"],
      managedBy: ui.integration.managedBy,
      source: ui.integration.source,
      requiresAuth: ui.integration.requiresAuth,
      authType: ui.integration.authType,
      tools: ui.integration.tools,
      iconUrl: ui.integration.iconUrl ?? undefined,
      isPublic: ui.integration.isPublic ?? undefined,
      createdBy: ui.integration.createdBy ?? undefined,
      isFeatured: ui.integration.isFeatured,
      displayPriority: ui.integration.displayPriority,
      slug: ui.integration.slug,
    }));

    const userIntegrationIds = new Set(
      userIntegrations.map((ui) => ui.integrationId),
    );

    // Add platform integrations not yet in user's list
    const platformIntegrations = configResponse.integrations;
    const availablePlatformIntegrations: Integration[] = platformIntegrations
      .filter((pi) => !userIntegrationIds.has(pi.id))
      .map((pi) => {
        const status = statuses.find((s) => s.integrationId === pi.id);
        return {
          id: pi.id,
          name: pi.name,
          description: pi.description,
          category: (pi.category || "other") as IntegrationCategoryValue,
          status: status?.connected
            ? ("connected" as const)
            : ("not_connected" as const),
          isSpecial: pi.isSpecial,
          displayPriority: pi.displayPriority,
          includedIntegrations: pi.includedIntegrations,
          isFeatured: pi.isFeatured,
          available: pi.available,
          managedBy: pi.managedBy as Integration["managedBy"],
          source: "platform" as const,
          authType: pi.authType as Integration["authType"],
          iconUrl: pi.iconUrl,
          slug: pi.slug || pi.id,
        };
      });

    const allIntegrations = [
      ...userIntegrationsList,
      ...availablePlatformIntegrations,
    ];

    // Sort: created first, then connected, then not_connected, alphabetically within
    const statusPriority: Record<string, number> = {
      created: 0,
      connected: 1,
      not_connected: 2,
      error: 3,
    };

    return allIntegrations.sort((a, b) => {
      const priorityA = statusPriority[a.status] ?? 3;
      const priorityB = statusPriority[b.status] ?? 3;
      if (priorityA !== priorityB) return priorityA - priorityB;
      return a.name.localeCompare(b.name);
    });
  } catch (error) {
    console.error("Error fetching integrations:", error);
    return [];
  }
}

export async function fetchIntegrationsStatus(): Promise<
  IntegrationsStatusResponse["integrations"]
> {
  try {
    const response = await apiService.get<IntegrationsStatusResponse>(
      "/integrations/status",
    );
    return response.integrations;
  } catch (error) {
    console.error("Error fetching integrations status:", error);
    return [];
  }
}

export interface ConnectIntegrationResult {
  success: boolean;
  cancelled?: boolean;
  error?: string;
  status?: string;
  toolsCount?: number;
}

/**
 * Connect an integration via OAuth browser flow.
 */
export async function connectIntegration(
  integrationId: string,
): Promise<ConnectIntegrationResult> {
  try {
    const redirectUri = Linking.createURL("integrations/callback");
    const authUrl = `${API_ORIGIN}/api/v1/integrations/login/${integrationId}?redirect_path=${encodeURIComponent(redirectUri)}`;
    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUri);

    if (result.type === "success") {
      return { success: true, status: "connected" };
    } else if (result.type === "cancel") {
      return { success: false, cancelled: true };
    } else {
      return { success: false, error: "Authentication failed" };
    }
  } catch (error) {
    console.error("Error connecting integration:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Connection failed",
    };
  }
}

/**
 * Connect an integration using a bearer token (API key).
 * POSTs the token to the backend which persists it and marks the integration connected.
 */
export async function connectIntegrationWithToken(
  integrationId: string,
  bearerToken: string,
): Promise<ConnectIntegrationResult> {
  try {
    await apiService.post(`/integrations/${integrationId}/token`, {
      bearer_token: bearerToken,
    });
    return { success: true, status: "connected" };
  } catch (error) {
    console.error("Error connecting integration with token:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Connection failed",
    };
  }
}

/**
 * Disconnect an integration using DELETE (matching web behavior)
 */
export async function disconnectIntegration(
  integrationId: string,
): Promise<boolean> {
  try {
    await apiService.delete(`/integrations/${integrationId}`);
    return true;
  } catch (error) {
    console.error("Error disconnecting integration:", error);
    return false;
  }
}

export interface CreateCustomIntegrationParams {
  name: string;
  description?: string;
  server_url: string;
  requires_auth?: boolean;
  auth_type?: "none" | "oauth" | "bearer";
  is_public?: boolean;
  bearer_token?: string;
}

export interface ConnectionTestResult {
  status: "connected" | "requires_oauth" | "failed" | "created";
  toolsCount?: number;
  oauthUrl?: string;
  error?: string;
}

export interface CreateCustomIntegrationResponse {
  status: string;
  message: string;
  integrationId: string;
  name: string;
  connection?: ConnectionTestResult;
}

export async function createCustomIntegration(
  data: CreateCustomIntegrationParams,
): Promise<CreateCustomIntegrationResponse> {
  const response = await apiService.post<CreateCustomIntegrationResponse>(
    "/integrations/custom",
    data,
  );
  return response;
}

export async function updateCustomIntegration(
  id: string,
  data: Partial<CreateCustomIntegrationParams>,
): Promise<CreateCustomIntegrationResponse> {
  const response = await apiService.put<CreateCustomIntegrationResponse>(
    `/integrations/custom/${id}`,
    data,
  );
  return response;
}

export async function deleteCustomIntegration(id: string): Promise<void> {
  await apiService.delete(`/integrations/custom/${id}`);
}

export async function getCommunityIntegrations(
  params?: CommunitySearchParams,
): Promise<CommunityIntegrationsResponse> {
  const searchParams = new URLSearchParams();
  if (params?.search) searchParams.set("search", params.search);
  if (params?.category) searchParams.set("category", params.category);
  if (params?.sort) searchParams.set("sort", params.sort);
  if (params?.limit != null) searchParams.set("limit", params.limit.toString());
  if (params?.offset != null)
    searchParams.set("offset", params.offset.toString());

  const query = searchParams.toString();
  return apiService.get<CommunityIntegrationsResponse>(
    `/integrations/community${query ? `?${query}` : ""}`,
  );
}

export async function getPublicIntegration(
  slug: string,
): Promise<PublicIntegrationResponse> {
  return apiService.get<PublicIntegrationResponse>(
    `/integrations/public/${slug}`,
  );
}

export async function addPublicIntegration(
  slug: string,
  bearerToken?: string,
): Promise<{
  status: string;
  integrationId: string;
  name: string;
  message: string;
  toolsCount?: number;
}> {
  return apiService.post<{
    status: string;
    integrationId: string;
    name: string;
    message: string;
    toolsCount?: number;
  }>(`/integrations/public/${slug}/add`, {
    bearer_token: bearerToken,
  });
}

export async function searchIntegrations(query: string): Promise<{
  integrations: PublicIntegrationResponse[];
  query: string;
}> {
  return apiService.get<{
    integrations: PublicIntegrationResponse[];
    query: string;
  }>(`/integrations/search?q=${encodeURIComponent(query)}`);
}

export async function publishIntegration(integrationId: string): Promise<{
  message: string;
  integrationId: string;
  publicUrl: string;
}> {
  return apiService.post<{
    message: string;
    integrationId: string;
    publicUrl: string;
  }>(`/integrations/custom/${integrationId}/publish`, {});
}

export async function unpublishIntegration(integrationId: string): Promise<{
  message: string;
  integrationId: string;
}> {
  return apiService.post<{
    message: string;
    integrationId: string;
  }>(`/integrations/custom/${integrationId}/unpublish`, {});
}

export const integrationsApi = {
  fetchIntegrations,
  fetchIntegrationsStatus,
  connectIntegration,
  connectIntegrationWithToken,
  disconnectIntegration,
  createCustomIntegration,
  updateCustomIntegration,
  deleteCustomIntegration,
  getCommunityIntegrations,
  getPublicIntegration,
  addPublicIntegration,
  searchIntegrations,
  publishIntegration,
  unpublishIntegration,
};
