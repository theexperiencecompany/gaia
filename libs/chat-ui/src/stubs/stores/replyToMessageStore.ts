/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
export interface ReplyToMessageData {
  id: string;
  content: string;
  role: "user" | "assistant";
}

interface ReplyToMessageState {
  replyToMessage: ReplyToMessageData | null;
  inputFocusCallback: (() => void) | null;
}

interface ReplyToMessageActions {
  setReplyToMessage: (message: ReplyToMessageData | null) => void;
  clearReplyToMessage: () => void;
  setInputFocusCallback: (callback: (() => void) | null) => void;
}

type ReplyToMessageStore = ReplyToMessageState & ReplyToMessageActions;

const noop = () => {};

const frozenState: ReplyToMessageStore = Object.freeze({
  replyToMessage: null,
  inputFocusCallback: null,
  setReplyToMessage: noop,
  clearReplyToMessage: noop,
  setInputFocusCallback: noop,
});

type Selector<U> = (state: ReplyToMessageStore) => U;

interface UseStoreFn {
  <U>(selector: Selector<U>): U;
  (): ReplyToMessageStore;
  getState: () => ReplyToMessageStore;
  setState: (partial: Partial<ReplyToMessageStore>) => void;
  subscribe: (listener: (state: ReplyToMessageStore) => void) => () => void;
}

export const useReplyToMessageStore: UseStoreFn = (<U,>(
  selector?: Selector<U>,
) => {
  if (selector) return selector(frozenState);
  return frozenState;
}) as UseStoreFn;
useReplyToMessageStore.getState = () => frozenState;
useReplyToMessageStore.setState = noop;
useReplyToMessageStore.subscribe = () => noop;

export const useReplyToMessage = () => ({
  replyToMessage: null as ReplyToMessageData | null,
  setReplyToMessage: noop as ReplyToMessageActions["setReplyToMessage"],
  clearReplyToMessage: noop as ReplyToMessageActions["clearReplyToMessage"],
  setInputFocusCallback:
    noop as ReplyToMessageActions["setInputFocusCallback"],
});
