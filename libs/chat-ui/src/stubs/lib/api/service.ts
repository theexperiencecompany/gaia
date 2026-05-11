/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
interface ApiOptions {
  successMessage?: string;
  errorMessage?: string;
  silent?: boolean;
}

export const apiService = {
  get: <T = unknown>(_url: string, _options?: ApiOptions): Promise<T> =>
    Promise.resolve(undefined as unknown as T),
  post: <T = unknown>(
    _url: string,
    _data?: unknown,
    _options?: ApiOptions,
  ): Promise<T> => Promise.resolve(undefined as unknown as T),
  put: <T = unknown>(
    _url: string,
    _data?: unknown,
    _options?: ApiOptions,
  ): Promise<T> => Promise.resolve(undefined as unknown as T),
  patch: <T = unknown>(
    _url: string,
    _data?: unknown,
    _options?: ApiOptions,
  ): Promise<T> => Promise.resolve(undefined as unknown as T),
  delete: <T = unknown>(
    _url: string,
    _dataOrOptions?: unknown | ApiOptions,
    _options?: ApiOptions,
  ): Promise<T> => Promise.resolve(undefined as unknown as T),
};
