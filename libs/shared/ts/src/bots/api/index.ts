import axios, { type AxiosInstance, type AxiosError } from "axios";
import type {
  AuthStatus,
  ChatRequest,
  ChatResponse,
  SessionInfo,
} from "../types";

interface RawChatResponse {
  response: string;
  conversation_id: string;
  authenticated: boolean;
}

interface RawSessionInfo {
  conversation_id: string;
  platform: string;
  platform_user_id: string;
}

interface RawAuthStatus {
  authenticated: boolean;
  platform: string;
  platform_user_id: string;
}

function formatApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const axiosErr = error as AxiosError;
    return `API error: ${axiosErr.response?.status ?? axiosErr.message}`;
  }
  if (error instanceof Error) return `API error: ${error.message}`;
  return "API error: unknown";
}

export class GaiaClient {
  private client: AxiosInstance;
  private baseUrl: string;

  constructor(baseUrl: string, apiKey: string) {
    this.baseUrl = baseUrl;
    this.client = axios.create({
      baseURL: baseUrl,
      timeout: 120_000,
      headers: {
        "Content-Type": "application/json",
        "X-Bot-API-Key": apiKey,
      },
    });
  }

  async chat(request: ChatRequest): Promise<ChatResponse> {
    try {
      const { data } = await this.client.post<RawChatResponse>(
        "/api/v1/bot/chat",
        {
          message: request.message,
          platform: request.platform,
          platform_user_id: request.platformUserId,
          channel_id: request.channelId,
          public_context: request.publicContext ?? false,
        },
      );

      return {
        response: data.response,
        conversationId: data.conversation_id,
        authenticated: data.authenticated,
      };
    } catch (error: unknown) {
      throw new Error(formatApiError(error));
    }
  }

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
      const { data } = await this.client.get<RawSessionInfo>(
        `/api/v1/bot/session/${platform}/${platformUserId}?${params.toString()}`,
      );
      return {
        conversationId: data.conversation_id,
        platform: data.platform,
        platformUserId: data.platform_user_id,
      };
    } catch (error: unknown) {
      throw new Error(formatApiError(error));
    }
  }

  async newSession(
    platform: string,
    platformUserId: string,
    channelId?: string,
  ): Promise<{ message: string }> {
    try {
      const { data } = await this.client.post<{ message: string }>(
        "/api/v1/bot/session/new",
        {
          platform,
          platform_user_id: platformUserId,
          channel_id: channelId,
        },
      );
      return data;
    } catch (error: unknown) {
      throw new Error(formatApiError(error));
    }
  }

  async checkAuthStatus(
    platform: string,
    platformUserId: string,
  ): Promise<AuthStatus> {
    try {
      const { data } = await this.client.get<RawAuthStatus>(
        `/api/v1/bot-auth/status/${platform}/${platformUserId}`,
      );
      return {
        authenticated: data.authenticated,
        platform: data.platform,
        platformUserId: data.platform_user_id,
      };
    } catch (error: unknown) {
      throw new Error(formatApiError(error));
    }
  }

  getAuthUrl(platform: string, platformUserId: string): string {
    const params = new URLSearchParams({
      platform_user_id: platformUserId,
    });
    return `${this.baseUrl}/api/v1/bot-auth/link/${platform}?${params.toString()}`;
  }
}
