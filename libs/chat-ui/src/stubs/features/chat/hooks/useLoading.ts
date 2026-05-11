/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
const noop = () => {};
const noopAsync = async () => {};

export const useLoading = () => ({
  isLoading: false,
  loadingText: "",
  loadingTextKey: 0,
  setIsLoading: noop as (loading: boolean) => void,
  setAbortController: noop as (controller: AbortController | null) => void,
  stopStream: noopAsync as () => Promise<void>,
});
