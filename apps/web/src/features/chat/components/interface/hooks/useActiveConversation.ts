"use client";

import { useEffect } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { db } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import {
  useDiscoveredConversationId,
  useVoiceModeActive,
} from "@/stores/voiceModeStore";

/**
 * Points the chat store at the conversation this route is showing and marks it
 * read on open.
 *
 * During a new voice session (no URL param) it uses the voice store's
 * provisional UUID, so this parent effect cannot overwrite VoiceSessionInner's
 * id with null.
 */
export const useActiveConversation = (convoIdParam: string): void => {
  const voiceModeActive = useVoiceModeActive();
  const storeDiscoveredId = useDiscoveredConversationId();
  const setActiveConversationId = useChatStore(
    (state) => state.setActiveConversationId,
  );

  useEffect(() => {
    if (voiceModeActive && !convoIdParam && storeDiscoveredId) {
      setActiveConversationId(storeDiscoveredId);
    } else {
      setActiveConversationId(convoIdParam || null);
    }

    if (convoIdParam) {
      const conversations = useChatStore.getState().conversations;
      const conversation = conversations.find((c) => c.id === convoIdParam);
      if (conversation?.isUnread) {
        useChatStore
          .getState()
          .upsertConversation({ ...conversation, isUnread: false });
        db.updateConversationFields(convoIdParam, { isUnread: false });
        chatApi.markAsRead(convoIdParam).catch(console.error);
      }
      // Freshness sync happens in useStreamResume, sequenced after the
      // live-turn discovery so it can't sweep an in-flight optimistic message.
    }

    return () => {
      useChatStore.getState().clearOptimisticMessage();
    };
  }, [
    convoIdParam,
    setActiveConversationId,
    voiceModeActive,
    storeDiscoveredId,
    // NOTE: Not including conversations or upsertConversation in deps
    // to avoid re-triggering when manually toggling read/unread status
  ]);
};
