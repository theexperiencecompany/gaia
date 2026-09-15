import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { getErrorMessage } from "@/lib/api/errors";
import { toast } from "@/lib/toast";
import { apiauth } from "./client";

export interface ApiOptions {
  successMessage?: string;
  errorMessage?: string;
  silent?: boolean;
}

/** Query parameters; `undefined` entries are dropped by axios. */
export type QueryParams = Record<string, unknown>;

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

const DEFAULT_ERROR_MESSAGES: Record<HttpMethod, string> = {
  GET: "Failed to fetch data",
  POST: "Failed to create data",
  PUT: "Failed to update data",
  PATCH: "Failed to update data",
  DELETE: "Failed to delete data",
};

/**
 * Generic API request handler with consistent error handling and toasting
 * @param method - HTTP method
 * @param url - API endpoint
 * @param data - Request body (for POST/PUT)
 * @param options - Configuration options
 * @returns Promise with response data
 */
export async function request<T = unknown>(
  method: HttpMethod,
  url: string,
  data?: unknown,
  options: ApiOptions = {},
  params?: QueryParams,
): Promise<T> {
  try {
    const config = method === "DELETE" && data ? { data } : {};
    const response = await apiauth.request({
      method,
      url,
      data: ["POST", "PUT", "PATCH"].includes(method) ? data : undefined,
      params,
      // FastAPI reads a list query param as repeated keys (`labels=a&labels=b`);
      // axios's default `labels[]=a` is invisible to it.
      paramsSerializer: { indexes: null },
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

    // A 402 the interceptor recognised is already `handled` (it opened the
    // paywall) — a "subscribe" toast on top would be noise. One it deliberately
    // left unhandled (a non-subscription_required body) belongs here, or the click does nothing.
    if (!options.silent && !handledByInterceptor && !isAuthError) {
      // Try to extract error message from various response formats, falling
      // back to a method-specific default.
      const errorMessage =
        options.errorMessage ||
        getErrorMessage(err.response?.data) ||
        DEFAULT_ERROR_MESSAGES[method];

      toast?.error?.(errorMessage);
    }

    throw error;
  }
}

/** API service wrapping `request` with consistent toast/error options across verbs. */
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
