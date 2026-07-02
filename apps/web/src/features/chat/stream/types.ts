import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import type { ReplyToMessageData } from "@/stores/replyToMessageStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";

export interface TurnOptions {
  fileData: FileData[];
  selectedTool: string | null;
  toolCategory: string | null;
  selectedWorkflow: WorkflowData | null;
  selectedCalendarEvent: SelectedCalendarEventData | null;
  optimisticUserId: string | null;
  replyToMessage: ReplyToMessageData | null;
  /** Conversation to stream into; null starts a new conversation. */
  conversationId: string | null;
  isOnboardingDemo: boolean;
}

/** One send request — either starts a turn session or waits in its queue. */
export interface SendArgs {
  inputText: string;
  userMessage: MessageType;
  options: TurnOptions;
}
