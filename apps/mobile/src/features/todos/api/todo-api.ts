import { createTodoApi, type HttpAdapter } from "@gaia/shared/todos";
import { apiService } from "@/lib/api";

const httpAdapter: HttpAdapter = {
  get: (url, _options) => apiService.get(url),
  post: (url, data, _options) => apiService.post(url, data),
  put: (url, data, _options) => apiService.put(url, data),
  patch: (url, data, _options) => apiService.patch(url, data),
  delete: (url, data, _options) => apiService.delete(url, data),
};

export const todoApi = createTodoApi(httpAdapter);
