import { getUserTimezone } from "@gaia/shared/api";
import {
  clearAuthData,
  getAuthToken,
} from "@/features/auth/utils/auth-storage";
import { API_BASE_URL } from "./constants";

// Callback invoked when any request returns 401 Unauthorized.
// Wired up by AuthProvider via setOnUnauthorized() so that the auth layer
// can clear stored credentials and redirect to login without creating a
// circular dependency between api.ts and the React context.
let onUnauthorizedCallback: (() => void) | null = null;

export function setOnUnauthorized(callback: () => void): void {
  onUnauthorizedCallback = callback;
}

interface ApiOptions {
  silent?: boolean;
}

interface RequestConfig {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  url: string;
  data?: unknown;
  options?: ApiOptions;
}

async function request<T = unknown>(config: RequestConfig): Promise<T> {
  const { method, url, data, options: _options = {} } = config;

  const token = await getAuthToken();
  if (!token) {
    throw new Error("Not authenticated");
  }

  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: "application/json",
    "x-timezone": getUserTimezone(),
  };

  if (data && !(data instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const fetchConfig: RequestInit = {
    method,
    headers,
    credentials: "include",
  };

  if (data) {
    fetchConfig.body = data instanceof FormData ? data : JSON.stringify(data);
  }

  const fullUrl = `${API_BASE_URL}${url}`;
  const response = await fetch(fullUrl, fetchConfig);

  if (!response.ok) {
    // Expired / revoked token — clear local credentials and notify the app.
    if (response.status === 401) {
      await clearAuthData();
      onUnauthorizedCallback?.();
    }

    const errorText = await response.text();
    console.error(`[API] Error ${response.status}: ${errorText}`);
    throw new Error(`API request failed: ${response.status}`);
  }

  const contentType = response.headers.get("content-type");
  if (contentType?.includes("application/json")) {
    return response.json();
  }

  return {} as T;
}

export const apiService = {
  get: <T = unknown>(url: string, options?: ApiOptions) =>
    request<T>({ method: "GET", url, options }),

  post: <T = unknown>(url: string, data?: unknown, options?: ApiOptions) =>
    request<T>({ method: "POST", url, data, options }),

  put: <T = unknown>(url: string, data?: unknown, options?: ApiOptions) =>
    request<T>({ method: "PUT", url, data, options }),

  patch: <T = unknown>(url: string, data?: unknown, options?: ApiOptions) =>
    request<T>({ method: "PATCH", url, data, options }),

  delete: <T = unknown>(url: string, data?: unknown, options?: ApiOptions) =>
    request<T>({ method: "DELETE", url, data, options }),
};

export { API_BASE_URL };
