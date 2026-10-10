import { apiauth } from "./client";
import {
  type ApiOptions,
  announceSuccess,
  type HttpMethod,
  isHandled,
  reportFailure,
  toApiError,
} from "./outcome";

export type { ApiOptions };

/** Query parameters; `undefined` entries are dropped by axios. */
export type QueryParams = Record<string, unknown>;

/**
 * The URL-string request engine behind `apiService`.
 *
 * Feature code never calls this — it goes through the path-typed client in
 * ./typed. This exists for `@shared/todos`, whose client is also mobile's and
 * so keeps its routes as strings.
 */
async function request<T = unknown>(
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

    announceSuccess(options);

    return response.data;
  } catch (error: unknown) {
    throw reportFailure(
      method,
      url,
      toApiError(error),
      options,
      isHandled(error),
    );
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
