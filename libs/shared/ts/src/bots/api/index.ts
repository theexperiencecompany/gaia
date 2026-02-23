import type { Readable } from "node:stream";
import axios, { type AxiosInstance } from "axios";
import type {
  AuthStatus,
  BotUserContext,
  ChatRequest,
  Conversation,
  ConversationListResponse,
  CreateTodoRequest,
  SettingsResponse,
  Todo,
  TodoListResponse,
  Workflow,
  WorkflowExecutionRequest,
  WorkflowExecutionResponse,
  WorkflowListResponse,
} from "../types";

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
   * Streams a chat response via SSE (authenticated users only).
   */
  async chatStream(
    request: ChatRequest,
    onChunk: (text: string) => void | Promise<void>,
    onDone: (fullText: string, conversationId: string) => void | Promise<void>,
    onError: (error: Error) => void | Promise<void>,
  ): Promise<string> {
    return this._chatStreamWithRetry(
      request,
      onChunk,
      onDone,
      onError,
      "/api/v1/bot/chat-stream",
    );
  }

  /**
   * Wrapper that adds retry logic for transient failures.
   */
  private async _chatStreamWithRetry(
    request: ChatRequest,
    onChunk: (text: string) => void | Promise<void>,
    onDone: (fullText: string, conversationId: string) => void | Promise<void>,
    onError: (error: Error) => void | Promise<void>,
    endpoint: string,
    maxRetries = 2,
  ): Promise<string> {
    const retryableErrors = [
      "ECONNRESET",
      "socket hang up",
      "ETIMEDOUT",
      "ECONNREFUSED",
      "Connection interrupted",
      "Connection lost before receiving a response",
    ];

    let lastError: Error | null = null;
    let attemptedRetries = 0;

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        return await this._chatStreamInternal(
          request,
          onChunk,
          onDone,
          onError,
          attempt > 0,
          endpoint,
        );
      } catch (error: unknown) {
        lastError = error instanceof Error ? error : new Error(String(error));
        const errorMsg = lastError.message;

        // Check if this is a retryable error
        const isRetryable = retryableErrors.some((retryableErr) =>
          errorMsg.includes(retryableErr)
        );

        if (!isRetryable || attempt === maxRetries) {
          // Non-retryable error or max retries reached
          await onError(lastError);
          throw lastError;
        }

        // Wait before retrying (exponential backoff)
        const delayMs = Math.min(1000 * Math.pow(2, attempt), 5000);
        attemptedRetries++;
        console.log(
          `Retrying stream (attempt ${attemptedRetries}/${maxRetries}) after ${delayMs}ms...`
        );
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }

    // Should never reach here, but just in case
    const finalError = lastError || new Error("Stream failed after retries");
    await onError(finalError);
    throw finalError;
  }

  private async _chatStreamInternal(
    request: ChatRequest,
    onChunk: (text: string) => void | Promise<void>,
    onDone: (fullText: string, conversationId: string) => void | Promise<void>,
    onError: (error: Error) => void | Promise<void>,
    retried: boolean,
    endpoint: string,
  ): Promise<string> {
    let fullText = "";
    let conversationId = "";
    let streamError: Error | null = null;

    // Increased timeouts for slow API operations (lazy loading, cold starts, etc.)
    const STREAM_TIMEOUT_MS = 600_000; // 10 minutes - overall connection timeout
    const INACTIVITY_TIMEOUT_MS = 300_000; // 5 minutes - no data received timeout

    const ctx = {
      platform: request.platform,
      platformUserId: request.platformUserId,
      channelId: request.channelId,
    };

    try {
      const response = await this.client.post(
        endpoint,
        {
          message: request.message,
          platform: request.platform,
          platform_user_id: request.platformUserId,
          channel_id: request.channelId,
        },
        {
          responseType: "stream",
          timeout: STREAM_TIMEOUT_MS,
          headers: {
            Accept: "text/event-stream",
            ...this.userHeaders(ctx),
          },
        },
      );

      const stream = response.data as Readable;
      let buffer = "";
      let finished = false;
      let inactivityTimer: ReturnType<typeof setTimeout> | null = null;
      let lastActivity = Date.now();
      let receivedKeepalive = false;

      const resetInactivityTimer = (resolve: () => void) => {
        if (inactivityTimer) clearTimeout(inactivityTimer);
        lastActivity = Date.now();
        inactivityTimer = setTimeout(async () => {
          if (!finished) {
            finished = true;
            stream.destroy();
            if (fullText) {
              // If we got some content, consider it a success
              await onDone(fullText, conversationId);
            } else {
              // No content after timeout - this is an error
              const errorMsg = receivedKeepalive
                ? "The AI is taking longer than expected. Please try a simpler request or try again later."
                : "Connection timeout - no response from server. Please try again.";
              await onError(new Error(errorMsg));
            }
            resolve();
          }
        }, INACTIVITY_TIMEOUT_MS);
      };

      await new Promise<void>((resolve) => {
        resetInactivityTimer(resolve);

        stream.on("data", async (rawChunk: Buffer) => {
          if (finished) return;
          try {
            resetInactivityTimer(resolve);
            buffer += rawChunk.toString();
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
              if (finished) return;
              const trimmed = line.trim();

              if (!trimmed || !trimmed.startsWith("data: ")) continue;
              const raw = trimmed.slice(6);
              if (raw === "[DONE]") continue;

              try {
                const data = JSON.parse(raw);
                if (data.keepalive) {
                  // Server keepalive ping to keep the connection alive
                  receivedKeepalive = true;
                  continue;
                }
                if (data.error === "not_authenticated") {
                  finished = true;
                  if (inactivityTimer) clearTimeout(inactivityTimer);
                  await onError(new Error("not_authenticated"));
                  resolve();
                  return;
                }
                if (data.error) {
                  finished = true;
                  if (inactivityTimer) clearTimeout(inactivityTimer);
                  await onError(new Error(data.error));
                  resolve();
                  return;
                }
                if (data.session_token) {
                  const sessionKey = this.getSessionKey(ctx);
                  this.sessionTokens.set(sessionKey, {
                    token: data.session_token,
                    expiresAt: Date.now() + TOKEN_TTL_MS,
                  });
                }
                if (data.text) {
                  fullText += data.text;
                  onChunk(data.text);
                }
                if (data.done) {
                  finished = true;
                  if (inactivityTimer) clearTimeout(inactivityTimer);
                  conversationId = data.conversation_id || "";
                  await onDone(fullText, conversationId);
                  resolve();
                  return;
                }
              } catch (parseErr) {
                if (!(parseErr instanceof SyntaxError)) {
                  finished = true;
                  if (inactivityTimer) clearTimeout(inactivityTimer);
                  await onError(
                    parseErr instanceof Error
                      ? parseErr
                      : new Error("Stream processing failed"),
                  );
                  resolve();
                  return;
                }
              }
            }
          } catch {
            // Prevent unhandled rejection if a callback throws
            if (!finished) {
              finished = true;
              if (inactivityTimer) clearTimeout(inactivityTimer);
              resolve();
            }
          }
        });

        stream.on("end", async () => {
          if (inactivityTimer) clearTimeout(inactivityTimer);
          try {
            if (!finished) {
              finished = true;
              if (fullText) {
                // Got partial response - return what we have
                await onDone(fullText, conversationId);
              } else if (receivedKeepalive) {
                // Received keepalive but no content - server is working but slow
                await onError(
                  new Error("The AI is processing your request but hasn't responded yet. Please try again."),
                );
              } else {
                // No keepalive, no content - connection issue
                await onError(
                  new Error("Connection lost before receiving a response. Please try again."),
                );
              }
            }
          } catch {
            // Prevent unhandled rejection if a callback throws
          } finally {
            resolve();
          }
        });

        stream.on("error", async (err: Error) => {
          if (inactivityTimer) clearTimeout(inactivityTimer);
          try {
            if (!finished) {
              finished = true;
              const isRetryable =
                err.message.includes("ECONNRESET") ||
                err.message.includes("socket hang up") ||
                err.message.includes("ETIMEDOUT");

              if (isRetryable && !fullText) {
                // No content received yet — store for re-throw so _chatStreamWithRetry can retry
                streamError = err;
              } else {
                // Has partial content or non-retryable — surface to user
                const errorMsg =
                  err.message.includes("ECONNRESET") || err.message.includes("socket hang up")
                    ? "Connection interrupted. Please try again."
                    : err.message.includes("timeout")
                    ? "Request timed out. The server may be busy - please try again."
                    : err.message;
                await onError(new Error(errorMsg));
              }
            }
          } catch {
            // Prevent unhandled rejection if callback throws
          } finally {
            resolve();
          }
        });
      });
    } catch (error: unknown) {
      const status = (error as { response?: { status?: number } })?.response
        ?.status;

      if (status === 401 && !retried) {
        this.clearSessionToken(ctx);
        return this._chatStreamInternal(
          request,
          onChunk,
          onDone,
          onError,
          true,
          endpoint,
        );
      }

      // Re-throw so _chatStreamWithRetry can classify the error and retry if appropriate
      throw error;
    }

    // Re-throw retryable mid-stream errors so _chatStreamWithRetry can retry them.
    // These are stored rather than thrown inside the stream event handler because
    // stream errors resolve the promise (not reject it).
    if (streamError) {
      throw streamError;
    }

    return conversationId;
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
        selectedModelName: data.selected_model_name ?? null,
        selectedModelIconUrl: data.selected_model_icon_url ?? null,
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
  async listWorkflows(ctx: BotUserContext): Promise<WorkflowListResponse> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.get<WorkflowListResponse>(
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
  ): Promise<Workflow> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.post<{ workflow: Workflow }>(
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
  ): Promise<Workflow> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.get<{ workflow: Workflow }>(
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
    request: WorkflowExecutionRequest,
    ctx: BotUserContext,
  ): Promise<WorkflowExecutionResponse> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.post<WorkflowExecutionResponse>(
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
      await this.client.delete(`/api/v1/workflows/${encodeURIComponent(workflowId)}`, {
        headers: this.userHeaders(ctx),
      });
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
  ): Promise<TodoListResponse> {
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
    request: CreateTodoRequest,
    ctx: BotUserContext,
  ): Promise<Todo> {
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
  async getTodo(todoId: string, ctx: BotUserContext): Promise<Todo> {
    return this.requestWithAuth(async () => {
      const { data } = await this.client.get(`/api/v1/todos/${encodeURIComponent(todoId)}`, {
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
    updates: Partial<CreateTodoRequest>,
    ctx: BotUserContext,
  ): Promise<Todo> {
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
  async completeTodo(todoId: string, ctx: BotUserContext): Promise<Todo> {
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
  ): Promise<ConversationListResponse> {
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
  ): Promise<Conversation> {
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
  async unlinkAccount(
    platform: string,
    platformUserId: string,
  ): Promise<void> {
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
function mapTodoResponse(data: Record<string, unknown>): Todo {
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
function mapConversationResponse(data: Record<string, unknown>): Conversation {
  return {
    conversation_id:
      (data.conversation_id as string) || (data.id as string) || "",
    title: (data.title as string) || (data.description as string) || undefined,
    created_at: (data.createdAt as string) || (data.created_at as string) || "",
    updated_at: (data.updatedAt as string) || (data.updated_at as string) || "",
    message_count: data.message_count as number | undefined,
  };
}
