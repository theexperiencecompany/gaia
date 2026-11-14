"use client";

import { useRoomContext, useTranscriptions } from "@livekit/components-react";
import type { TextStreamReader } from "livekit-client";
import { useCallback, useEffect, useRef } from "react";
import {
  LK_CHAT_TOPIC,
  VOICE_STREAM_TOPIC,
} from "@/features/chat/components/voice-agent/constants";
import { track } from "@/lib/analytics";
import { useChatStore } from "@/stores/chatStore";
import { useVoiceModeActions } from "@/stores/voiceModeStore";

/** Read the conversation id the voice agent announces in-band on its display topic. */
async function readAnnouncedConversationId(
  reader: TextStreamReader,
): Promise<string | null> {
  const raw = await reader.readAll();
  const event: unknown = JSON.parse(raw);
  if (typeof event !== "object" || event === null) return null;
  const id = (event as { conversation_id?: unknown }).conversation_id;
  return typeof id === "string" && id ? id : null;
}

/**
 * Wire a voice session to its conversation. Every row on screen, spoken turns
 * included, comes from the conversation's event stream; the room only names
 * the conversation and carries typed turns to the agent.
 */
export function useVoiceMessages(conversationId: string | null): {
  sendUserTurn: (text: string) => Promise<void>;
} {
  const room = useRoomContext();
  const transcriptions = useTranscriptions();
  const { setDiscoveredConversationId } = useVoiceModeActions();
  /** Transcription stream ids already counted as a received utterance. */
  const seenTranscriptionIdsRef = useRef<Set<string>>(new Set());

  // The in-band id survives a dropped send on the separate conversation-id topic.
  useEffect(() => {
    if (!room) return;
    const handler = (reader: TextStreamReader) => {
      readAnnouncedConversationId(reader)
        .then((id) => {
          if (id) setDiscoveredConversationId(id);
        })
        .catch((error: unknown) => {
          console.error("[useVoiceMessages] Unreadable voice event:", error);
        });
    };
    room.registerTextStreamHandler(VOICE_STREAM_TOPIC, handler);
    return () => {
      room.unregisterTextStreamHandler(VOICE_STREAM_TOPIC);
    };
  }, [room, setDiscoveredConversationId]);

  useEffect(() => {
    if (!room) return;
    const localIdentity = room.localParticipant.identity;
    for (const transcription of transcriptions) {
      const id = transcription.streamInfo.id;
      if (
        transcription.participantInfo.identity !== localIdentity ||
        !transcription.text.trim() ||
        seenTranscriptionIdsRef.current.has(id)
      ) {
        continue;
      }
      seenTranscriptionIdsRef.current.add(id);
      track("voice:transcription_received", {
        conversation_id: conversationId ?? undefined,
      });
    }
  }, [transcriptions, room, conversationId]);

  useEffect(() => {
    if (!conversationId) return;
    useChatStore.getState().setActiveConversationId(conversationId);
  }, [conversationId]);

  // A typed turn has no transcription: the agent posts it like a spoken one.
  const sendUserTurn = useCallback(
    async (text: string): Promise<void> => {
      const trimmed = text.trim();
      if (!trimmed || !room) return;
      await room.localParticipant.sendText(trimmed, { topic: LK_CHAT_TOPIC });
    },
    [room],
  );

  return { sendUserTurn };
}
