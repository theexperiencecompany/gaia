import { createTodoApi, type HttpAdapter } from "@shared/todos";
import { apiService } from "@/lib/api/service";

const httpAdapter: HttpAdapter = {
  get: (url, options) => apiService.get(url, options),
  post: (url, data, options) => apiService.post(url, data, options),
  put: (url, data, options) => apiService.put(url, data, options),
  patch: (url, data, options) => apiService.patch(url, data, options),
  delete: (url, data, options) => apiService.delete(url, data, options),
};

export const todoApi = createTodoApi(httpAdapter);
