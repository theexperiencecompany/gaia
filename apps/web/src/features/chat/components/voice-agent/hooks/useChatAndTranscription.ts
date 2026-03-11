import {
  type ReceivedChatMessage,
  type TextStreamData,
  useChat,
  useRoomContext,
  useTranscriptions,
} from "@livekit/components-react";
import { useMemo } from "react";
import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import { transcriptionToChatMessage } from "@/features/chat/utils/voiceUtils";
import type { MessageType } from "@/types/features/convoTypes";

export default function useChatAndTranscription(
  toolDataEntries: ToolDataEntry[] = [],
  followUpActions: string[] = [],
) {
  const transcriptions: TextStreamData[] = useTranscriptions();
  const chat = useChat();
  const room = useRoomContext();

  const mergedTranscriptions = useMemo(() => {
    const merged: Array<ReceivedChatMessage> = [
      ...transcriptions.map((transcription) =>
        transcriptionToChatMessage(transcription, room),
      ),
      ...chat.chatMessages,
    ];
    return merged.sort((a, b) => a.timestamp - b.timestamp);
  }, [transcriptions, chat.chatMessages, room]);

  // Map to MessageType[], enriching the last bot message with tool data and follow-up actions
  const mappedMessages = useMemo(() => {
    const mapped = mergedTranscriptions.map(mapLivekitToMessageType);
    if (toolDataEntries.length === 0 && followUpActions.length === 0) {
      return mapped;
    }
    // Find last bot message and attach tool data / follow-up actions
    const lastBotIdx = [...mapped].reverse().findIndex((m) => m.type === "bot");
    if (lastBotIdx === -1) return mapped;
    const actualIdx = mapped.length - 1 - lastBotIdx;
    return mapped.map((msg, i) => {
      if (i !== actualIdx) return msg;
      return {
        ...msg,
        tool_data: toolDataEntries.length > 0 ? toolDataEntries : msg.tool_data,
        follow_up_actions:
          followUpActions.length > 0 ? followUpActions : msg.follow_up_actions,
      };
    });
  }, [mergedTranscriptions, toolDataEntries, followUpActions]);

  return { messages: mappedMessages };
}

function mapLivekitToMessageType(entry: ReceivedChatMessage): MessageType {
  return {
    type: entry.from?.isLocal ? "user" : "bot",
    message_id: entry.id,
    response: entry.message,
    date: new Date(entry.timestamp).toISOString(),
    loading: false,
    disclaimer: undefined,
  };
}
