import { toast } from "sonner";

import { apiauth } from "./client";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

interface ApiOptions {
  successMessage?: string;
  errorMessage?: string;
  silent?: boolean;
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
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
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

    const err = error as { response?: { status?: number; data?: unknown }; message?: string };
    const isUnauthorized = err.response?.status === 401;

    // Track API errors in PostHog
    trackEvent(ANALYTICS_EVENTS.API_ERROR, {
      method,
      url,
      status: err.response?.status,
      error_message: err.message,
    });

    if (!options.silent && !isUnauthorized) {
      const defaultMessages = {
        GET: "Failed to fetch data",
        POST: "Failed to create data",
        PUT: "Failed to update data",
        PATCH: "Failed to update data",
        DELETE: "Failed to delete data",
      };
      toast?.error?.(options.errorMessage || defaultMessages[method]);
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
