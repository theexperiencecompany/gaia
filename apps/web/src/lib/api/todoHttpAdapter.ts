import type { HttpAdapter } from "@shared/todos";
import { apiService } from "./service";

/**
 * The URL-string adapter `@shared/todos` builds its client on. The shared
 * client is also mobile's, so its routes stay strings; this is the one place
 * in web that hands it the request engine.
 */
export const todoHttpAdapter: HttpAdapter = {
  get: (url, options) => apiService.get(url, options),
  post: (url, data, options) => apiService.post(url, data, options),
  put: (url, data, options) => apiService.put(url, data, options),
  patch: (url, data, options) => apiService.patch(url, data, options),
  delete: (url, data, options) => apiService.delete(url, data, options),
};
