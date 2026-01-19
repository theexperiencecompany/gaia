import type { ChatRequest, ChatResponse, SessionInfo, AuthStatus } from "../types";
import axios, { type AxiosInstance } from "axios";

/**
 * Client for interacting with the GAIA Backend Bot API.
 * Handles authentication, chat interactions, sessions, and platform linking status.
 */
export class GaiaClient {
  private client: AxiosInstance;
  private baseUrl: string;

  /**
   * Creates a new GaiaClient instance.
   *
   * @param baseUrl - The base URL of the GAIA API (e.g., http://localhost:8000)
   * @param apiKey - The secure bot API key for server-to-server communication
   */
  constructor(baseUrl: string, apiKey: string) {
    this.baseUrl = baseUrl;
    this.client = axios.create({
      baseURL: baseUrl,
      headers: {
        "Content-Type": "application/json",
        "X-Bot-API-Key": apiKey
      }
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
      const { data } = await this.client.post<any>("/api/v1/bot/chat", {
        message: request.message,
        platform: request.platform,
        platform_user_id: request.platformUserId,
        channel_id: request.channelId
      });

      return {
        response: data.response,
        conversationId: data.conversation_id,
        authenticated: data.authenticated
      };
    } catch (error: any) {
      throw new Error(`API error: ${error.response?.status || error.message}`);
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
      const { data } = await this.client.post<any>("/api/v1/bot/chat/public", {
        message: request.message,
        platform: request.platform,
        platform_user_id: request.platformUserId
      });

      return {
        response: data.response,
        conversationId: data.conversation_id,
        authenticated: false
      };
    } catch (error: any) {
      throw new Error(`API error: ${error.response?.status || error.message}`);
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
    channelId?: string
  ): Promise<SessionInfo> {
    const params = new URLSearchParams();
    if (channelId) {
      params.set("channel_id", channelId);
    }

    try {
      const { data } = await this.client.get<SessionInfo>(
        `/api/v1/bot/session/${platform}/${platformUserId}?${params.toString()}`
      );
      return data;
    } catch (error: any) {
      throw new Error(`API error: ${error.response?.status || error.message}`);
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
  async checkAuthStatus(platform: string, platformUserId: string): Promise<AuthStatus> {
    try {
      const { data } = await this.client.get<AuthStatus>(
        `/api/v1/bot-auth/status/${platform}/${platformUserId}`
      );
      return data;
    } catch (error: any) {
      throw new Error(`API error: ${error.response?.status || error.message}`);
    }
  }

  /**
   * Generates a URL for the user to authenticate and link their account.
   *
   * @param platform - The platform name.
   * @param platformUserId - The platform user ID.
   * @returns The full URL for authentication.
   */
  getAuthUrl(platform: string, platformUserId: string): string {
    const params = new URLSearchParams({
      platform,
      platform_user_id: platformUserId
    });
    return `${this.baseUrl}/bot-auth/link/${platform}?${params.toString()}`; // Adjusted URL path to match backend
  }
}
