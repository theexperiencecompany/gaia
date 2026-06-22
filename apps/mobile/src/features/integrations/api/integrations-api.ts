import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { apiService } from "@/lib/api";
import { API_ORIGIN } from "@/lib/constants";
import type {
  CommunityIntegrationsResponse,
  CommunitySearchParams,
  Integration,
  IntegrationCategoryValue,
  IntegrationTool,
  IntegrationToolsResponse,
  MyIntegrationItem,
  MyIntegrationsResponse,
  PublicIntegrationResponse,
} from "../types";

WebBrowser.maybeCompleteAuthSession();

// Display order: created (added but unconnected) first, then connected, then
// the rest of the catalog. Matches the previous client-side merge ordering.
const STATUS_PRIORITY: Record<Integration["status"], number> = {
  created: 0,
  connected: 1,
  not_connected: 2,
};

/**
 * Map one personalized catalog entry (`GET /integrations/me`) to the mobile
 * `Integration` UI type. Per-tool schemas are not included here — the detail
 * sheet fetches them on demand via `getIntegrationTools`.
 */
function toIntegration(item: MyIntegrationItem): Integration {
  return {
    id: item.id,
    name: item.name,
    description: item.description,
    category: (item.category || "other") as IntegrationCategoryValue,
    status: item.status,
    slug: item.slug ?? item.id,
    isFeatured: item.isFeatured,
    displayPriority: item.displayPriority,
    available: item.available,
    managedBy: item.managedBy,
    source: item.source,
    requiresAuth: item.requiresAuth,
    authType: item.authType ?? undefined,
    iconUrl: item.iconUrl ?? undefined,
    isPublic: item.isPublic ?? undefined,
    createdBy: item.createdBy ?? undefined,
    creator: item.creator,
  };
}

/**
 * Fetch the user's full integration catalog (platform + their own custom
 * integrations), each carrying connection status, in a single request.
 */
export async function fetchIntegrations(): Promise<Integration[]> {
  try {
    const response =
      await apiService.get<MyIntegrationsResponse>("/integrations/me");

    return response.integrations.map(toIntegration).sort((a, b) => {
      const priorityA = STATUS_PRIORITY[a.status];
      const priorityB = STATUS_PRIORITY[b.status];
      if (priorityA !== priorityB) return priorityA - priorityB;
      return a.name.localeCompare(b.name);
    });
  } catch (error) {
    console.error("Error fetching integrations:", error);
    return [];
  }
}

/**
 * Fetch the full tool list for a single integration on demand. The catalog
 * endpoint (`/integrations/me`) only returns `toolCount`, so the detail view
 * loads names/descriptions from here when opened.
 */
export async function getIntegrationTools(
  integrationId: string,
): Promise<IntegrationTool[]> {
  const response = await apiService.get<IntegrationToolsResponse>(
    `/integrations/${integrationId}/tools`,
  );
  return response.tools;
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
  getIntegrationTools,
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
