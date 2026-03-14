export interface ApiClientConfig {
  baseUrl: string;
  getToken: () => Promise<string | null>;
  timeout?: number;
}

export class ApiError extends Error {
  status: number;
  code: string | undefined;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/**
 * Build the standard request headers, including Authorization if a token is present.
 */
export function createApiHeaders(token: string | null): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  return headers;
}

/**
 * Build a full URL from a base, a path segment, and optional query parameters.
 * Removes duplicate slashes at the base/path boundary.
 */
export function buildUrl(
  base: string,
  path: string,
  params?: Record<string, unknown>,
): string {
  const normalizedBase = base.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(`${normalizedBase}${normalizedPath}`);

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }

  return url.toString();
}
