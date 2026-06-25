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
import { streamChat } from "./chat-stream";

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
  private baseUrl: string;
  private frontendUrl: string;
  private apiKey: string;
  private sessionTokens: Map<string, TokenEntry> = new Map();

  constructor(baseUrl: string, apiKey: string, frontendUrl: string) {
    this.baseUrl = baseUrl;
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
      const status = (error as { response?: { status?: number } })?.response
        ?.status;
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
      const status = (error as { response?: { status?: number } })?.response
        ?.status;

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
   * Gets a specific todo by ID.
   */
  async getTodo(todoId: string, ctx: BotUserContext): Promise<BotTodo> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.get(
        `/api/v1/todos/${encodeURIComponent(todoId)}`,
        {
          headers: this.userHeaders(ctx),
        },
      );
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

  /**
   * Gets a specific conversation by ID.
   */
  async getConversation(
    conversationId: string,
    ctx: BotUserContext,
  ): Promise<BotConversation> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.get(
        `/api/v1/conversations/${encodeURIComponent(conversationId)}`,
        { headers: this.userHeaders(ctx) },
      );
      return mapConversationResponse(data);
    }, ctx);
  }

  getConversationUrl(conversationId: string): string {
    return `${this.frontendUrl}/c/${conversationId}`;
  }

  /** Upgrade/pricing page, surfaced in rate-limit replies for free users. */
  getPricingUrl(): string {
    return `${this.frontendUrl}/pricing`;
  }

  getBaseUrl(): string {
    return this.baseUrl;
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
   * Uploads a binary file to GAIA's shared file storage on behalf of the
   * authenticated bot user. The returned {@link BotFileData} can be sent
   * alongside the next chat request via `fileIds` / `fileData` so the agent
   * grounds its reply in the uploaded content.
   *
   * Uses the same `/api/v1/upload` endpoint as the web app — the bot auth
   * middleware resolves the linked user from `X-Bot-API-Key` + platform
   * headers, so no separate bot-only upload route is required.
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
    return this.requestWithAuth(async () => {
      const form = new FormData();
      // A File (carrying name + type) preserves the mime type for FastAPI's
      // UploadFile content_type, which file_service.py uses to dispatch
      // image/PDF/text summarisation. A File with a 2-arg append (vs a Blob
      // with a 3-arg append) keeps the typings consistent under lib:ESNext,
      // where the 3-arg FormData.append overload isn't resolved.
      const file = new File([new Uint8Array(input.data)], input.filename, {
        type: input.mimeType,
      });
      form.append("file", file);
      if (input.conversationId) {
        form.append("conversation_id", input.conversationId);
      }

      const { data } = await this.client.post("/api/v1/upload", form, {
        headers: {
          ...this.userHeaders(ctx),
          // The axios instance defaults Content-Type to application/json, which
          // makes axios JSON-encode FormData instead of sending multipart (the
          // backend then sees no `file` field and returns 422). Force multipart
          // here — axios fills in the boundary from the FormData.
          "Content-Type": "multipart/form-data",
        },
        // Allow uploads up to the backend's 10 MB cap plus multipart overhead.
        maxBodyLength: 12 * 1024 * 1024,
        maxContentLength: 12 * 1024 * 1024,
      });

      return {
        fileId: data.fileId,
        url: data.url,
        filename: data.filename,
        type: data.type ?? "file",
        message: data.message,
      };
    }, ctx);
  }

  /**
   * Downloads a session artifact's bytes (a file the agent wrote to
   * `artifacts/`) on behalf of the authenticated bot user. Used to deliver
   * agent-generated documents to a messaging platform: the bot fetches the
   * bytes here, then uploads them via the platform's media API.
   *
   * Hits the same authenticated `GET /api/v1/sessions/{conv}/artifacts/{path}`
   * route the web app uses; the bot auth middleware resolves the linked user
   * and the endpoint enforces conversation ownership.
   */
  async downloadArtifact(
    conversationId: string,
    path: string,
    ctx: BotUserContext,
  ): Promise<{ data: Buffer; contentType: string }> {
    return this.requestWithAuth(async () => {
      const encodedPath = path
        .split("/")
        .map((seg) => encodeURIComponent(seg))
        .join("/");
      const { data, headers } = await this.client.get(
        `/api/v1/sessions/${encodeURIComponent(conversationId)}/artifacts/${encodedPath}`,
        {
          responseType: "arraybuffer",
          headers: this.userHeaders(ctx),
          // 100 MB = the largest per-platform outbound cap (WhatsApp). A lower
          // cap here would reject 50–100 MB artifacts as transport errors before
          // OUTBOUND_FILE_LIMITS can apply the platform limit or graceful note.
          maxContentLength: 100 * 1024 * 1024,
          maxBodyLength: 100 * 1024 * 1024,
        },
      );
      const contentType = String(
        headers["content-type"] ?? "application/octet-stream",
      );
      return { data: Buffer.from(data as ArrayBuffer), contentType };
    }, ctx);
  }

  /**
   * Transcribes a short audio clip (voice note or audio file) to text via the
   * bot transcription endpoint, which proxies to OpenAI Whisper server-side.
   *
   * Returns the transcribed text. Throws {@link GaiaApiError} on failure so
   * callers can fall back to a "couldn't understand audio" reply.
   */
  async transcribeAudio(
    input: {
      data: Buffer;
      filename: string;
      mimeType: string;
    },
    ctx: BotUserContext,
  ): Promise<string> {
    return this.requestWithAuth(async () => {
      const form = new FormData();
      const file = new File([new Uint8Array(input.data)], input.filename, {
        type: input.mimeType,
      });
      form.append("file", file);

      const { data } = await this.client.post("/api/v1/bot/transcribe", form, {
        headers: {
          ...this.userHeaders(ctx),
          // Force multipart so axios doesn't JSON-encode the FormData (the
          // instance default Content-Type is application/json). See uploadFile.
          "Content-Type": "multipart/form-data",
        },
        maxBodyLength: 30 * 1024 * 1024,
        maxContentLength: 30 * 1024 * 1024,
      });

      return String(data.text ?? "").trim();
    }, ctx);
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
