import axios, { type AxiosInstance } from "axios";
import type {
  AuthStatus,
  ChatRequest,
  ChatResponse,
  ConnectedIntegration,
  SessionInfo,
  UserSettings,
} from "../types";

/**
 * Client for interacting with the GAIA Backend Bot API.
 * Handles authentication, chat interactions, sessions, and platform linking status.
 */
export class GaiaClient {
  private client: AxiosInstance;
  private webUrl: string;

  /**
   * Creates a new GaiaClient instance.
   *
   * @param baseUrl - The base URL of the GAIA API (e.g., http://localhost:8000)
   * @param apiKey - The secure bot API key for server-to-server communication
   * @param webUrl - The base URL of the GAIA web app (e.g., https://heygaia.io)
   */
  constructor(baseUrl: string, apiKey: string, webUrl = "https://heygaia.io") {
    this.webUrl = webUrl;
    this.client = axios.create({
      baseURL: baseUrl,
      headers: {
        "Content-Type": "application/json",
        "X-Bot-API-Key": apiKey,
      },
    });
  }

  /**
   * Sends a chat message to the GAIA agent on behalf of an authenticated user.
   *
   * @param request - The chat request containing message, platform, and user ID.
   * @returns The agent's response and session details.
   * @throws Error if the API request fails.
   */
  async chat(request: ChatRequest): Promise<ChatResponse> {
    try {
      const { data } = await this.client.post<{
        response: string;
        conversation_id: string;
        authenticated: boolean;
      }>("/api/v1/bot/chat", {
        message: request.message,
        platform: request.platform,
        platform_user_id: request.platformUserId,
        channel_id: request.channelId,
      });

      return {
        response: data.response,
        conversationId: data.conversation_id,
        authenticated: data.authenticated,
      };
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status || "unknown";
        const message = error.response?.data?.detail || error.message;
        throw new Error(`API error (${status}): ${message}`);
      }
      throw error instanceof Error ? error : new Error("Unknown error");
    }
  }

  /**
   * Sends a public (unauthenticated) chat message to the GAIA agent.
   * This is used for public mentions where user identity is not strictly linked.
   *
   * @param request - The chat request containing message and platform details.
   * @returns The agent's response.
   * @throws Error if the API request fails.
   */
  async chatPublic(request: ChatRequest): Promise<ChatResponse> {
    try {
      const { data } = await this.client.post<{
        response: string;
        conversation_id: string;
        authenticated: boolean;
      }>("/api/v1/bot/chat/public", {
        message: request.message,
        platform: request.platform,
        platform_user_id: request.platformUserId,
      });

      return {
        response: data.response,
        conversationId: data.conversation_id,
        authenticated: false,
      };
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status || "unknown";
        const message = error.response?.data?.detail || error.message;
        throw new Error(`API error (${status}): ${message}`);
      }
      throw error instanceof Error ? error : new Error("Unknown error");
    }
  }

  /**
   * Retrieves or creates a session for a user on a specific platform.
   *
   * @param platform - The platform name (discord, slack, telegram).
   * @param platformUserId - The user's ID on that platform.
   * @param channelId - Optional channel ID to scope the session.
   * @returns Session information including conversation ID.
   * @throws Error if the API request fails.
   */
  async getSession(
    platform: string,
    platformUserId: string,
    channelId?: string,
  ): Promise<SessionInfo> {
    const params = new URLSearchParams();
    if (channelId) {
      params.set("channel_id", channelId);
    }

    try {
      const { data } = await this.client.get<SessionInfo>(
        `/api/v1/bot/session/${platform}/${platformUserId}?${params.toString()}`,
      );
      return data;
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status || "unknown";
        const message = error.response?.data?.detail || error.message;
        throw new Error(`API error (${status}): ${message}`);
      }
      throw error instanceof Error ? error : new Error("Unknown error");
    }
  }

  /**
   * Checks if a platform user is linked to a GAIA account.
   *
   * @param platform - The platform name.
   * @param platformUserId - The platform user ID.
   * @returns Authentication status.
   * @throws Error if the API request fails.
   */
  async checkAuthStatus(
    platform: string,
    platformUserId: string,
  ): Promise<AuthStatus> {
    try {
      const { data } = await this.client.get<AuthStatus>(
        `/api/v1/bot/auth/status/${platform}/${platformUserId}`,
      );
      return data;
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status || "unknown";
        const message = error.response?.data?.detail || error.message;
        throw new Error(`API error (${status}): ${message}`);
      }
      throw error instanceof Error ? error : new Error("Unknown error");
    }
  }

  /**
   * Generates a URL for the user to authenticate and link their platform account.
   * Users should be directed to the GAIA Settings → Linked Accounts page to connect
   * their platform account securely via OAuth.
   *
   * @returns The URL to the GAIA settings/linked-accounts page.
   */
  getAuthUrl(): string {
    return `${this.webUrl}/settings?section=linked-accounts`;
  }

  /**
   * Retrieves user settings including profile, integrations, and selected model.
   *
   * @param platform - The platform name.
   * @param platformUserId - The platform user ID.
   * @returns User settings information.
   * @throws Error if the API request fails.
   */
  async getSettings(
    platform: string,
    platformUserId: string,
  ): Promise<UserSettings> {
    try {
      const { data } = await this.client.get<{
        authenticated: boolean;
        user_name: string | null;
        profile_image_url: string | null;
        account_created_at: string | null;
        selected_model_name: string | null;
        selected_model_icon_url: string | null;
        connected_integrations: Array<{
          id: string;
          name: string;
          icon_url: string | null;
        }>;
      }>(`/api/v1/bot/settings/${platform}/${platformUserId}`);

      return {
        authenticated: data.authenticated,
        userName: data.user_name,
        profileImageUrl: data.profile_image_url,
        accountCreatedAt: data.account_created_at,
        selectedModelName: data.selected_model_name,
        selectedModelIconUrl: data.selected_model_icon_url,
        connectedIntegrations: data.connected_integrations.map(
          (i): ConnectedIntegration => ({
            id: i.id,
            name: i.name,
            iconUrl: i.icon_url,
          }),
        ),
      };
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status || "unknown";
        const message = error.response?.data?.detail || error.message;
        throw new Error(`API error (${status}): ${message}`);
      }
      throw error instanceof Error ? error : new Error("Unknown error");
    }
  }
}
