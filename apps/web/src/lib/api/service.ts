import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import { apiauth } from "./client";

interface ApiOptions {
  successMessage?: string;
  errorMessage?: string;
  silent?: boolean;
}

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

const DEFAULT_ERROR_MESSAGES: Record<HttpMethod, string> = {
  GET: "Failed to fetch data",
  POST: "Failed to create data",
  PUT: "Failed to update data",
  PATCH: "Failed to update data",
  DELETE: "Failed to delete data",
};

/**
 * Extract a human-readable error message from the various shapes the backend
 * (and upstream services) use for error payloads. Returns undefined when no
 * message can be found, so the caller can fall back to a default.
 */
function extractErrorMessageFromData(data: unknown): string | undefined {
  if (typeof data !== "object" || data === null) return undefined;

  const errorData = data as Record<string, unknown>;

  // Format 1: { detail: { message: "..." } }
  if (
    errorData.detail &&
    typeof errorData.detail === "object" &&
    errorData.detail !== null
  ) {
    const detail = errorData.detail as Record<string, unknown>;
    return typeof detail.message === "string" ? detail.message : undefined;
  }
  // Format 2: { detail: "..." }
  if (typeof errorData.detail === "string") {
    return errorData.detail;
  }
  // Format 3: { message: "..." }
  if (typeof errorData.message === "string") {
    return errorData.message;
  }
  // Format 4: { error: "..." } or { error: { message: "..." } }
  if (errorData.error) {
    if (typeof errorData.error === "string") {
      return errorData.error;
    }
    if (typeof errorData.error === "object" && errorData.error !== null) {
      const errorObj = errorData.error as Record<string, unknown>;
      if (typeof errorObj.message === "string") {
        return errorObj.message;
      }
    }
  }

  return undefined;
}

/**
 * Generic API request handler with consistent error handling and toasting
 * @param method - HTTP method
 * @param url - API endpoint
 * @param data - Request body (for POST/PUT)
 * @param options - Configuration options
 * @returns Promise with response data
 */
async function request<T = unknown>(
  method: HttpMethod,
  url: string,
  data?: unknown,
  options: ApiOptions = {},
): Promise<T> {
  try {
    const config = method === "DELETE" && data ? { data } : {};
    const response = await apiauth.request({
      method,
      url,
      data: ["POST", "PUT", "PATCH"].includes(method) ? data : undefined,
      ...config,
    });

    if (options.successMessage && !options.silent) {
      toast.success(options.successMessage);
    }

    return response.data;
  } catch (error: unknown) {
    console.error(`${method} ${url} failed:`, error);

    const err = error as {
      response?: {
        status?: number;
        data?: unknown;
      };
      message?: string;
    };

    // The interceptor (processAxiosError) toasts and marks errors it handles
    // (network, 401/403/429/5xx). Don't double-toast those.
    const handledByInterceptor =
      (error as { handled?: boolean }).handled === true;

    // 401 means "not authenticated" — an expected state for anonymous visitors
    // on public pages (which don't mount the interceptor). The app shell surfaces
    // it via the login modal; never toast it as a generic error.
    const isAuthError = err.response?.status === 401;

    // Track failed requests in PostHog (client-only; analytics.ts is "use client")
    if (globalThis.window !== undefined) {
      trackEvent(ANALYTICS_EVENTS.API_REQUEST_FAILED, {
        method,
        // Strip query strings — they can carry search terms, tokens, or other
        // sensitive values that must never reach PostHog.
        url: url.split("?")[0],
        status: err.response?.status,
        error_message: err.message,
      });
    }

    if (!options.silent && !handledByInterceptor && !isAuthError) {
      // Try to extract error message from various response formats, falling
      // back to a method-specific default.
      const errorMessage =
        options.errorMessage ||
        extractErrorMessageFromData(err.response?.data) ||
        DEFAULT_ERROR_MESSAGES[method];

      toast?.error?.(errorMessage);
    }

    throw error;
  }
}

/**
 * Simple API service with consistent patterns
 *
 * @example
 * // Fetching data
 * const users = await apiService.get<User[]>('/users');
 *
 * // Fetching with error handling
 * const profile = await apiService.get<UserProfile>('/profile', {
 *   errorMessage: 'Failed to load profile'
 * });
 *
 * // Creating data with success message
 * const newPost = await apiService.post<Post>('/posts',
 *   { title: 'Hello', content: 'World' },
 *   { successMessage: 'Post created!', errorMessage: 'Failed to create post' }
 * );
 *
 * // Updating data
 * const updated = await apiService.put<Todo>(`/todos/${id}`,
 *   { completed: true },
 *   { successMessage: 'Task completed!' }
 * );
 *
 * // Deleting data
 * await apiService.delete(`/posts/${id}`, {
 *   successMessage: 'Post deleted',
 *   errorMessage: 'Failed to delete post'
 * });
 *
 * // Patching data
 * await apiService.patch('/users/profile',
 *   { avatar: 'new-url' },
 *   { silent: true } // No toasts
 * );
 */
export const apiService = {
  get: <T = unknown>(url: string, options?: ApiOptions) =>
    request<T>("GET", url, undefined, options),
  post: <T = unknown>(url: string, data?: unknown, options?: ApiOptions) =>
    request<T>("POST", url, data, options),
  put: <T = unknown>(url: string, data?: unknown, options?: ApiOptions) =>
    request<T>("PUT", url, data, options),
  patch: <T = unknown>(url: string, data?: unknown, options?: ApiOptions) =>
    request<T>("PATCH", url, data, options),
  delete: <T = unknown>(
    url: string,
    dataOrOptions?: unknown | ApiOptions,
    options?: ApiOptions,
  ) => {
    // Handle both delete(url, options) and delete(url, data, options)
    if (
      dataOrOptions &&
      typeof dataOrOptions === "object" &&
      ("successMessage" in dataOrOptions ||
        "errorMessage" in dataOrOptions ||
        "silent" in dataOrOptions)
    ) {
      return request<T>("DELETE", url, undefined, dataOrOptions as ApiOptions);
    }
    return request<T>("DELETE", url, dataOrOptions, options);
  },
};
