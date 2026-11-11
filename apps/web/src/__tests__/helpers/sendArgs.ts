import type { SendArgs } from "@/features/chat/stream/types";

/** A plain text send into an existing conversation, the shape a TurnSession is built from. */
export function textSendArgs(conversationId: string, text: string): SendArgs {
  return {
    inputText: text,
    userMessage: {
      type: "user",
      response: text,
      date: new Date().toISOString(),
      message_id: "msg-1",
    },
    options: {
      fileData: [],
      selectedTool: null,
      toolCategory: null,
      selectedWorkflow: null,
      selectedCalendarEvent: null,
      optimisticUserId: "opt-1",
      replyToMessage: null,
      conversationId,
      isOnboardingDemo: false,
      isRetry: false,
    },
  };
}
