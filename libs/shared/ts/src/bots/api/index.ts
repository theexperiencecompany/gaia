import axios, { type AxiosInstance } from "axios";
import type {
  AuthStatus,
  BotConversation,
  BotConversationListResponse,
  BotCreateTodoRequest,
  BotFileData,
  BotTodo,
  BotTodoListResponse,
  BotUserContext,
  BotWorkflow,
  BotWorkflowExecutionRequest,
  BotWorkflowExecutionResponse,
  BotWorkflowListResponse,
  ChatRequest,
  SettingsResponse,
} from "../types";
import { getHttpStatus } from "../utils/logger";
import { streamChat } from "./chat-stream";
import {
  downloadArtifactRequest,
  transcribeAudioRequest,
  uploadFileRequest,
} from "./media";

export class GaiaApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "GaiaApiError";
    this.status = status;
  }
}

/**
 * Client for interacting with the GAIA Backend API.
 *
 * Bot requests are authenticated via:
 * 1. X-Bot-API-Key + X-Bot-Platform + X-Bot-Platform-User-Id headers
 *    (handled by BotAuthMiddleware which sets request.state.user)
 * 2. Optional Authorization: Bearer <jwt> for faster subsequent requests
 *
 * This allows bots to use the same endpoints as the web app.
 */
/** Session token entry with TTL. */
interface TokenEntry {
  token: string;
  expiresAt: number;
}

/**
 * Client-side TTL for cached session tokens.
 * Set to 12 minutes — slightly under the server's 15-minute expiry —
 * so the client proactively evicts tokens before the server rejects them,
 * preventing unnecessary 401 → retry round-trips.
 */
const TOKEN_TTL_MS = 12 * 60 * 1000;

export class GaiaClient {
  private client: AxiosInstance;
  private frontendUrl: string;
  private apiKey: string;
  private sessionTokens: Map<string, TokenEntry> = new Map();

  constructor(baseUrl: string, apiKey: string, frontendUrl: string) {
    this.frontendUrl = frontendUrl;
    this.apiKey = apiKey;
    this.client = axios.create({
      baseURL: baseUrl,
      headers: {
        "Content-Type": "application/json",
      },
    });
  }

  private getSessionKey(ctx: BotUserContext): string {
    return `${ctx.platform}:${ctx.platformUserId}`;
  }

  /**
   * Build headers for authenticated bot requests.
   * Always includes X-Bot-API-Key and platform headers.
   * Optionally includes JWT session token for faster auth.
   */
  private userHeaders(ctx: BotUserContext) {
    const sessionKey = this.getSessionKey(ctx);
    const entry = this.sessionTokens.get(sessionKey);
    const sessionToken =
      entry && entry.expiresAt > Date.now() ? entry.token : undefined;
    if (entry && !sessionToken) this.sessionTokens.delete(sessionKey);

    const headers: Record<string, string> = {
      "X-Bot-API-Key": this.apiKey,
      "X-Bot-Platform": ctx.platform,
      "X-Bot-Platform-User-Id": ctx.platformUserId,
    };

    if (sessionToken) {
      headers.Authorization = `Bearer ${sessionToken}`;
    }

    return headers;
  }

  private clearSessionToken(ctx: BotUserContext): void {
    const sessionKey = this.getSessionKey(ctx);
    this.sessionTokens.delete(sessionKey);
  }

  private async request<T>(fn: () => Promise<T>): Promise<T> {
    try {
      return await fn();
    } catch (error: unknown) {
      if (error instanceof GaiaApiError) throw error;
      const message = error instanceof Error ? error.message : "Unknown error";
      const status = getHttpStatus(error);
      throw new GaiaApiError(`API error: ${status || message}`, status);
    }
  }

  private async requestWithAuth<T>(
    fn: () => Promise<T>,
    ctx: BotUserContext,
    retried = false,
  ): Promise<T> {
    try {
      return await fn();
    } catch (error: unknown) {
      const status = getHttpStatus(error);

      if (status === 401 && !retried) {
        this.clearSessionToken(ctx);
        return this.requestWithAuth(fn, ctx, true);
      }

      if (error instanceof GaiaApiError) throw error;
      const message = error instanceof Error ? error.message : "Unknown error";
      throw new GaiaApiError(`API error: ${status || message}`, status);
    }
  }

  /**
   * Stores a fresh session token for the user with the client-side TTL.
   */
  private storeSessionToken(ctx: BotUserContext, token: string): void {
    this.sessionTokens.set(this.getSessionKey(ctx), {
      token,
      expiresAt: Date.now() + TOKEN_TTL_MS,
    });
  }

  /**
   * Streams a chat response via SSE (authenticated users only).
   */
  async chatStream(
    request: ChatRequest,
    onChunk: (text: string) => void | Promise<void>,
    onDone: (fullText: string, conversationId: string) => void | Promise<void>,
    onError: (error: Error) => void | Promise<void>,
  ): Promise<string> {
    return streamChat(
      {
        client: this.client,
        userHeaders: (ctx) => this.userHeaders(ctx),
        storeSessionToken: (ctx, token) => this.storeSessionToken(ctx, token),
        clearSessionToken: (ctx) => this.clearSessionToken(ctx),
      },
      request,
      onChunk,
      onDone,
      onError,
      "/api/v1/bot/chat-stream",
    );
  }

  /**
   * Checks if a platform user is linked to a GAIA account.
   */
  async checkAuthStatus(
    platform: string,
    platformUserId: string,
  ): Promise<AuthStatus> {
    return this.request(async () => {
      const { data } = await this.client.get<AuthStatus>(
        `/api/v1/bot/auth-status/${platform}/${platformUserId}`,
        {
          headers: {
            "X-Bot-API-Key": this.apiKey,
            "X-Bot-Platform": platform,
            "X-Bot-Platform-User-Id": platformUserId,
          },
        },
      );
      return data;
    });
  }

  /**
   * Lists the platform_user_ids linked on a platform. Bots use this on startup
   * to pre-warm caches (e.g. Discord DM channels) so cold inbound messages
   * resolve after a restart.
   */
  async listLinkedPlatformUserIds(platform: string): Promise<string[]> {
    return this.request(async () => {
      const { data } = await this.client.get<{ platform_user_ids: string[] }>(
        `/api/v1/bot/linked-users/${platform}`,
        {
          headers: {
            "X-Bot-API-Key": this.apiKey,
            "X-Bot-Platform": platform,
          },
        },
      );
      return data.platform_user_ids ?? [];
    });
  }

  /**
   * Gets user settings including account info, integrations, and selected model.
   */
  async getSettings(
    platform: string,
    platformUserId: string,
  ): Promise<SettingsResponse> {
    return this.request(async () => {
      const { data } = await this.client.get(
        `/api/v1/bot/settings/${platform}/${platformUserId}`,
        {
          headers: {
            "X-Bot-API-Key": this.apiKey,
            "X-Bot-Platform": platform,
            "X-Bot-Platform-User-Id": platformUserId,
          },
        },
      );
      return {
        authenticated: data.authenticated,
        userName: data.user_name ?? null,
        accountCreatedAt: data.account_created_at ?? null,
        profileImageUrl: data.profile_image_url ?? null,
        connectedIntegrations:
          data.connected_integrations?.map(
            (i: { name: string; logo_url?: string; status: string }) => ({
              name: i.name,
              logoUrl: i.logo_url ?? null,
              status: i.status,
            }),
          ) ?? [],
      };
    });
  }

  /**
   * Lists all workflows for the authenticated user.
   * Uses the regular /api/v1/workflows endpoint via bot middleware auth.
   */
  async listWorkflows(ctx: BotUserContext): Promise<BotWorkflowListResponse> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.get<BotWorkflowListResponse>(
        "/api/v1/workflows",
        { headers: this.userHeaders(ctx) },
      );
      return data;
    }, ctx);
  }

  /**
   * Creates a new workflow.
   */
  async createWorkflow(
    request: {
      name: string;
      description: string;
      steps?: Record<string, unknown>[];
    },
    ctx: BotUserContext,
  ): Promise<BotWorkflow> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.post<{ workflow: BotWorkflow }>(
        "/api/v1/workflows",
        request,
        { headers: this.userHeaders(ctx) },
      );
      return data.workflow;
    }, ctx);
  }

  /**
   * Gets a specific workflow by ID.
   */
  async getWorkflow(
    workflowId: string,
    ctx: BotUserContext,
  ): Promise<BotWorkflow> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.get<{ workflow: BotWorkflow }>(
        `/api/v1/workflows/${encodeURIComponent(workflowId)}`,
        { headers: this.userHeaders(ctx) },
      );
      return data.workflow;
    }, ctx);
  }

  /**
   * Executes a workflow.
   */
  async executeWorkflow(
    request: BotWorkflowExecutionRequest,
    ctx: BotUserContext,
  ): Promise<BotWorkflowExecutionResponse> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.post<BotWorkflowExecutionResponse>(
        `/api/v1/workflows/${encodeURIComponent(request.workflow_id)}/execute`,
        { inputs: request.inputs },
        { headers: this.userHeaders(ctx) },
      );
      return data;
    }, ctx);
  }

  /**
   * Deletes a workflow.
   */
  async deleteWorkflow(workflowId: string, ctx: BotUserContext): Promise<void> {
    return this.requestWithAuth(async () => {
      await this.client.delete(
        `/api/v1/workflows/${encodeURIComponent(workflowId)}`,
        {
          headers: this.userHeaders(ctx),
        },
      );
    }, ctx);
  }

  /**
   * Lists todos for the authenticated user.
   * Uses the regular /api/v1/todos endpoint via bot middleware auth.
   */
  async listTodos(
    ctx: BotUserContext,
    params?: {
      completed?: boolean;
      project_id?: string;
    },
  ): Promise<BotTodoListResponse> {
    return this.requestWithAuth(async () => {
      const queryParams = new URLSearchParams();
      if (params?.completed !== undefined) {
        queryParams.set("completed", String(params.completed));
      }
      if (params?.project_id) {
        queryParams.set("project_id", params.project_id);
      }

      const { data } = await this.client.get(
        `/api/v1/todos?${queryParams.toString()}`,
        { headers: this.userHeaders(ctx) },
      );

      // Map from regular API format (data/meta) to bot format (todos/total)
      const todos = (data.data || data.todos || []).map(mapTodoResponse);
      const total = data.meta?.total ?? data.total ?? todos.length;

      return { todos, total };
    }, ctx);
  }

  /**
   * Creates a new todo.
   */
  async createTodo(
    request: BotCreateTodoRequest,
    ctx: BotUserContext,
  ): Promise<BotTodo> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.post("/api/v1/todos", request, {
        headers: this.userHeaders(ctx),
      });
      return mapTodoResponse(data);
    }, ctx);
  }

  /**
   * Updates a todo.
   */
  async updateTodo(
    todoId: string,
    updates: Partial<BotCreateTodoRequest>,
    ctx: BotUserContext,
  ): Promise<BotTodo> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.put(
        `/api/v1/todos/${encodeURIComponent(todoId)}`,
        updates,
        { headers: this.userHeaders(ctx) },
      );
      return mapTodoResponse(data);
    }, ctx);
  }

  /**
   * Marks a todo as complete.
   */
  async completeTodo(todoId: string, ctx: BotUserContext): Promise<BotTodo> {
    return this.updateTodo(todoId, { completed: true }, ctx);
  }

  /**
   * Deletes a todo.
   */
  async deleteTodo(todoId: string, ctx: BotUserContext): Promise<void> {
    return this.requestWithAuth(async () => {
      await this.client.delete(`/api/v1/todos/${encodeURIComponent(todoId)}`, {
        headers: this.userHeaders(ctx),
      });
    }, ctx);
  }

  /**
   * Lists conversations for the authenticated user.
   * Uses the regular /api/v1/conversations endpoint via bot middleware auth.
   */
  async listConversations(
    ctx: BotUserContext,
    params?: {
      page?: number;
      limit?: number;
    },
  ): Promise<BotConversationListResponse> {
    return this.requestWithAuth(async () => {
      const queryParams = new URLSearchParams();
      queryParams.set("page", String(params?.page || 1));
      queryParams.set("limit", String(params?.limit || 10));

      const { data } = await this.client.get(
        `/api/v1/conversations?${queryParams.toString()}`,
        { headers: this.userHeaders(ctx) },
      );

      // Map from regular API format to bot format
      const conversations = (data.conversations || []).map(
        mapConversationResponse,
      );

      return {
        conversations,
        total: data.total ?? conversations.length,
        page: data.page ?? 1,
      };
    }, ctx);
  }

  /** Upgrade/pricing page, surfaced in rate-limit replies for free users. */
  getPricingUrl(): string {
    return `${this.frontendUrl}/pricing`;
  }

  getFrontendUrl(): string {
    return this.frontendUrl;
  }

  /**
   * Resets the bot session, starting a fresh conversation.
   * The previous conversation is preserved in the GAIA web app.
   */
  async resetSession(
    platform: string,
    platformUserId: string,
    channelId?: string,
  ): Promise<void> {
    return this.request(async () => {
      await this.client.post(
        "/api/v1/bot/reset-session",
        {
          platform,
          platform_user_id: platformUserId,
          channel_id: channelId ?? null,
        },
        {
          headers: {
            "X-Bot-API-Key": this.apiKey,
            "X-Bot-Platform": platform,
            "X-Bot-Platform-User-Id": platformUserId,
          },
        },
      );
    });
  }

  /**
   * Unlinks a platform account from the GAIA user.
   */
  async unlinkAccount(platform: string, platformUserId: string): Promise<void> {
    return this.request(async () => {
      await this.client.post(
        "/api/v1/bot/unlink",
        {},
        {
          headers: {
            "X-Bot-API-Key": this.apiKey,
            "X-Bot-Platform": platform,
            "X-Bot-Platform-User-Id": platformUserId,
          },
        },
      );
      this.sessionTokens.delete(`${platform}:${platformUserId}`);
    });
  }

  /**
   * Uploads a file to GAIA on behalf of the authenticated bot user. See
   * {@link uploadFileRequest}.
   */
  async uploadFile(
    input: {
      data: Buffer;
      filename: string;
      mimeType: string;
      conversationId?: string;
    },
    ctx: BotUserContext,
  ): Promise<BotFileData> {
    return this.requestWithAuth(
      () => uploadFileRequest(this.client, this.userHeaders(ctx), input),
      ctx,
    );
  }

  /**
   * Downloads a session artifact's bytes on behalf of the authenticated bot
   * user. See {@link downloadArtifactRequest}.
   */
  async downloadArtifact(
    conversationId: string,
    path: string,
    ctx: BotUserContext,
  ): Promise<{ data: Buffer; contentType: string }> {
    return this.requestWithAuth(
      () =>
        downloadArtifactRequest(
          this.client,
          this.userHeaders(ctx),
          conversationId,
          path,
        ),
      ctx,
    );
  }

  /**
   * Transcribes a short audio clip to text on behalf of the authenticated bot
   * user. See {@link transcribeAudioRequest}.
   */
  async transcribeAudio(
    input: {
      data: Buffer;
      filename: string;
      mimeType: string;
    },
    ctx: BotUserContext,
  ): Promise<string> {
    return this.requestWithAuth(
      () => transcribeAudioRequest(this.client, this.userHeaders(ctx), input),
      ctx,
    );
  }

  /**
   * Creates a secure, time-limited link token for platform account linking.
   * The token is stored in Redis and expires after 10 minutes.
   */
  async createLinkToken(
    platform: string,
    platformUserId: string,
    profile?: { username?: string; displayName?: string },
  ): Promise<{ token: string; authUrl: string }> {
    return this.request(async () => {
      const { data } = await this.client.post(
        "/api/v1/bot/create-link-token",
        {
          platform,
          platform_user_id: platformUserId,
          ...(profile?.username && { username: profile.username }),
          ...(profile?.displayName && { display_name: profile.displayName }),
        },
        {
          headers: {
            "X-Bot-API-Key": this.apiKey,
          },
        },
      );
      return {
        token: data.token,
        authUrl: data.auth_url,
      };
    });
  }
}

/**
 * Maps a todo response from the regular API format to the bot-expected format.
 */
function mapTodoResponse(data: Record<string, unknown>): BotTodo {
  return {
    id: (data.id as string) || "",
    title: (data.title as string) || "",
    description: data.description as string | undefined,
    completed: (data.completed as boolean) || false,
    priority: data.priority as "low" | "medium" | "high" | undefined,
    due_date: data.due_date as string | undefined,
    project_id: data.project_id as string | undefined,
  };
}

/**
 * Maps a conversation response from the regular API format to the bot-expected format.
 */
function mapConversationResponse(
  data: Record<string, unknown>,
): BotConversation {
  return {
    conversation_id:
      (data.conversation_id as string) || (data.id as string) || "",
    title: (data.title as string) || (data.description as string) || undefined,
    created_at: (data.createdAt as string) || (data.created_at as string) || "",
    updated_at: (data.updatedAt as string) || (data.updated_at as string) || "",
    message_count: data.message_count as number | undefined,
  };
}
