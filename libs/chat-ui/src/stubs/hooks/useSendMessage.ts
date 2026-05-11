/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import { useCallback } from "react";

import type { SelectedCalendarEventData } from "@/features/chat/hooks/useCalendarEventSelection";
import type { ReplyToMessageData } from "@/stores/replyToMessageStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";

type SendMessageOverrides = {
  files?: MessageType["fileData"];
  selectedTool?: string | null;
  selectedToolCategory?: string | null;
  selectedWorkflow?: WorkflowData | null;
  selectedCalendarEvent?: SelectedCalendarEventData | null;
  replyToMessage?: ReplyToMessageData | null;
  conversationId?: string | null;
};

export const useSendMessage = () => {
  return useCallback(
    async (_content: string, _overrides?: SendMessageOverrides) => {},
    [],
  );
};
