import type { MutableRefObject } from "react";
import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";

export type PendingStreamArgs = [
  inputText: string,
  currentMessages: MessageType[],
  fileData?: FileData[],
  selectedTool?: string | null,
  toolCategory?: string | null,
  selectedWorkflow?: WorkflowData | null,
  selectedCalendarEvent?: SelectedCalendarEventData | null,
  optimisticUserId?: string,
  replyToMessage?: {
    id: string;
    content: string;
    role: "user" | "assistant";
  } | null,
  conversationId?: string | null,
  isOnboardingDemo?: boolean,
];

export interface StreamRefs {
  convoMessages: MessageType[];
  botMessage: MessageType | null;
  userMessage: MessageType | null;
  optimisticUserId: string | null;
  accumulatedResponse: string;
  userPrompt: string;
  currentStreamingMessages: MessageType[];
  newConversation: {
    id: string | null;
    description: string | null;
  };
}

export interface LoadingTextOptions {
  toolName?: string;
  toolCategory?: string;
  integrationName?: string;
  iconUrl?: string;
  showCategory?: boolean;
}

export interface StreamContext {
  refs: MutableRefObject<StreamRefs>;
  persistTimerRef: MutableRefObject<ReturnType<typeof setTimeout> | null>;
  pendingStreamArgsRef: MutableRefObject<PendingStreamArgs | null>;
  streamInProgressRef: MutableRefObject<boolean>;
  streamCloseHandledRef: MutableRefObject<boolean>;
  setIsLoading: (loading: boolean) => void;
  setAbortController: (controller: AbortController | null) => void;
  setLoadingText: (text: string, opts?: LoadingTextOptions) => void;
  resetLoadingText: () => void;
}
