import {
  type ReceivedChatMessage,
  type TextStreamData,
  useChat,
  useRoomContext,
  useTranscriptions,
} from "@livekit/components-react";
import { useMemo } from "react";

import { transcriptionToChatMessage } from "@/features/chat/utils/voiceUtils";
import type { MessageType } from "@/types/features/convoTypes";

export default function useChatAndTranscription() {
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

  // Map to MessageType[]
  const mappedMessages = useMemo(
    () => mergedTranscriptions.map(mapLivekitToMessageType),
    [mergedTranscriptions],
  );

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
