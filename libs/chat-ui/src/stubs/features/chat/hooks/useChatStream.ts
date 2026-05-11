/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */

export interface ChatStreamState {
  isStreaming: boolean;
  streamId: string | null;
  abortStream: () => void;
}

export function useChatStream(): ChatStreamState {
  return {
    isStreaming: false,
    streamId: null,
    abortStream: () => {},
  };
}
