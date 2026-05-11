/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
type AnyFn = (...args: unknown[]) => Promise<{ data: unknown }>;

const stubResponse = () => Promise.resolve({ data: undefined as unknown });

const apiStub = {
  get: (() => stubResponse()) as AnyFn,
  post: (() => stubResponse()) as AnyFn,
  put: (() => stubResponse()) as AnyFn,
  patch: (() => stubResponse()) as AnyFn,
  delete: (() => stubResponse()) as AnyFn,
  request: (() => stubResponse()) as AnyFn,
  defaults: { timeout: 300_000, headers: {} },
  interceptors: {
    request: { use: () => 0, eject: () => {} },
    response: { use: () => 0, eject: () => {} },
  },
};

export const api = apiStub;
export const apiauth = apiStub;
