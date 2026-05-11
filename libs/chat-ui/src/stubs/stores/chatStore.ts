/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type { SelectedCalendarEventData } from "@/features/chat/hooks/useCalendarEventSelection";
import type { IConversation, IMessage } from "@/lib/db/chatDb";
import type { ReplyToMessageData } from "@/stores/replyToMessageStore";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";

interface OptimisticMessage {
  id: string;
  conversationId: string | null;
  content: string;
  role: "user" | "assistant";
  createdAt: Date;
  fileIds?: string[];
  fileData?: FileData[];
  toolName?: string | null;
  toolCategory?: string | null;
  workflowId?: string | null;
  selectedWorkflow?: WorkflowData | null;
  selectedCalendarEvent?: SelectedCalendarEventData | null;
  replyToMessage?: ReplyToMessageData | null;
  metadata?: Record<string, unknown>;
}

interface ChatState {
  conversations: IConversation[];
  messagesByConversation: Record<string, IMessage[]>;
  activeConversationId: string | null;
  streamingConversationId: string | null;
  hydrationCompleted: boolean;
  optimisticMessage: OptimisticMessage | null;
  setConversations: (conversations: IConversation[]) => void;
  upsertConversation: (conversation: IConversation) => void;
  updateConversation: (
    conversationId: string,
    updates: Partial<IConversation>,
  ) => void;
  setMessagesForConversation: (
    conversationId: string,
    messages: IMessage[],
  ) => void;
  addOrUpdateMessage: (message: IMessage) => void;
  removeConversation: (conversationId: string) => void;
  removeMessage: (messageId: string, conversationId: string) => void;
  setActiveConversationId: (id: string | null) => void;
  setStreamingConversationId: (id: string | null) => void;
  setHydrationCompleted: (completed: boolean) => void;
  setOptimisticMessage: (message: OptimisticMessage | null) => void;
  clearOptimisticMessage: () => void;
}

const noop = () => {};

const initialState: ChatState = {
  conversations: [],
  messagesByConversation: {},
  activeConversationId: null,
  streamingConversationId: null,
  hydrationCompleted: false,
  optimisticMessage: null,
  setConversations: noop,
  upsertConversation: noop,
  updateConversation: noop,
  setMessagesForConversation: noop,
  addOrUpdateMessage: noop,
  removeConversation: noop,
  removeMessage: noop,
  setActiveConversationId: noop,
  setStreamingConversationId: noop,
  setHydrationCompleted: noop,
  setOptimisticMessage: noop,
  clearOptimisticMessage: noop,
};

const frozenState = Object.freeze(initialState);

type Selector<U> = (state: ChatState) => U;

interface UseChatStoreFn {
  <U>(selector: Selector<U>): U;
  (): ChatState;
  getState: () => ChatState;
  setState: (partial: Partial<ChatState>) => void;
  subscribe: (listener: (state: ChatState) => void) => () => void;
}

export const useChatStore: UseChatStoreFn = (<U,>(selector?: Selector<U>) => {
  if (selector) return selector(frozenState);
  return frozenState;
}) as UseChatStoreFn;
useChatStore.getState = () => frozenState;
useChatStore.setState = noop;
useChatStore.subscribe = () => noop;

export const useChatStoreSync = (): void => {};
