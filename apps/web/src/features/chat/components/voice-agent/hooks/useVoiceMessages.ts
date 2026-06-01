"use client";

import { useRoomContext, useTranscriptions } from "@livekit/components-react";
import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";
import type { TextStreamReader } from "livekit-client";
import { useCallback, useEffect, useRef } from "react";
import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import { VOICE_STREAM_TOPIC } from "@/features/chat/components/voice-agent/constants";
import type { IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

interface VoiceBotTurn {
  localId: string;
  response: string;
  tool_data: ToolDataEntry[];
  follow_up_actions: string[];
  loading: boolean;
  startedAt: Date;
}

interface VoiceUserGroup {
  /** Used as the stable id suffix for this group's IMessage. */
  startStreamId: string;
  /** Per-stream text keyed by LiveKit stream id. Joined with NEW_MESSAGE_BREAK. */
  transcriptionTexts: Map<string, string>;
  startedAt: Date;
}

function turnToIMessage(turn: VoiceBotTurn, conversationId: string): IMessage {
  return {
    id: turn.localId,
    conversationId,
    content: turn.response,
    role: "assistant",
    status: turn.loading ? "sending" : "sent",
    createdAt: turn.startedAt,
    updatedAt: new Date(),
    tool_data: turn.tool_data.length > 0 ? turn.tool_data : null,
    follow_up_actions:
      turn.follow_up_actions.length > 0 ? turn.follow_up_actions : null,
    optimistic: true,
  };
}

function userGroupToIMessage(
  group: VoiceUserGroup,
  conversationId: string,
): IMessage {
  const content = Array.from(group.transcriptionTexts.values()).join(
    NEW_MESSAGE_BREAK_TOKEN,
  );
  return {
    id: `voice-user-${group.startStreamId}`,
    conversationId,
    content,
    role: "user",
    status: "sent",
    createdAt: group.startedAt,
    updatedAt: new Date(),
    optimistic: true,
  };
}

/**
 * Subscribes to LiveKit transcriptions + the agent's bot stream and writes
 * voice turns directly into `chatStore`. Side-effect only; returns nothing.
 *
 * Bot text arrives on the data channel as `event.response` (full unsanitized
 * text, matching what text mode renders). Plumbing events (`tool_data`,
 * `follow_up_actions`, `main_response_complete`) arrive on the same channel.
 * User speech is captured via `useTranscriptions()` filtered to the local
 * participant.
 */
export function useVoiceMessages(conversationId: string | null): void {
  const room = useRoomContext();
  const transcriptions = useTranscriptions();
  const addOrUpdateMessage = useChatStore((s) => s.addOrUpdateMessage);

  const activeTurnRef = useRef<VoiceBotTurn | null>(null);
  const currentUserGroupRef = useRef<VoiceUserGroup | null>(null);
  /** User transcription stream ids that have been flushed as part of a closed user group. */
  const consumedUserTranscriptionIdsRef = useRef<Set<string>>(new Set());
  const botTurnIndexRef = useRef(0);

  // Stash the latest conversationId in a ref so the bot-stream handler
  // closure (registered once with [room] deps) always sees the current value.
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;

  // Reset internal state on remount (new voice session).
  useEffect(() => {
    activeTurnRef.current = null;
    currentUserGroupRef.current = null;
    consumedUserTranscriptionIdsRef.current = new Set();
    botTurnIndexRef.current = 0;
  }, []);

  /**
   * Open a new bot turn. Closes the current user group (marking its
   * transcription ids consumed) so the next user transcription opens a fresh
   * group.
   */
  const openBotTurn = useCallback((): VoiceBotTurn => {
    const group = currentUserGroupRef.current;
    if (group) {
      for (const id of group.transcriptionTexts.keys()) {
        consumedUserTranscriptionIdsRef.current.add(id);
      }
      currentUserGroupRef.current = null;
    }
    botTurnIndexRef.current += 1;
    const idx = botTurnIndexRef.current;
    const sid = room?.name || "voice";
    const turn: VoiceBotTurn = {
      localId: `voice-bot-${sid}-${idx}-${Date.now()}`,
      response: "",
      tool_data: [],
      follow_up_actions: [],
      loading: true,
      startedAt: new Date(),
    };
    activeTurnRef.current = turn;
    return turn;
  }, [room]);

  // Bot stream handler — runs when the agent emits events on VOICE_STREAM_TOPIC.
  useEffect(() => {
    if (!room) return;

    const handler = async (reader: TextStreamReader) => {
      let rawEvent: string;
      try {
        rawEvent = await reader.readAll();
      } catch {
        return;
      }
      if (!rawEvent || rawEvent === "[DONE]") return;

      let event: Record<string, unknown>;
      try {
        event = JSON.parse(rawEvent) as Record<string, unknown>;
      } catch {
        return;
      }

      // Ignore plumbing events that don't render in the bubble. tool_output is
      // backend-internal; conversation_id/description are handled by a separate
      // text stream handler in VoiceControlBarContainer.
      if (
        "tool_output" in event ||
        "conversation_id" in event ||
        "conversation_description" in event
      ) {
        return;
      }

      const cid = conversationIdRef.current;
      if (!cid) return; // no conversation yet → nowhere to write

      // First content-bearing event of a new bot turn: open the turn.
      const turn = activeTurnRef.current ?? openBotTurn();

      let changed = false;
      if (typeof event.response === "string" && event.response) {
        turn.response += event.response;
        changed = true;
      } else if (event.tool_data && typeof event.tool_data === "object") {
        const entry = event.tool_data as ToolDataEntry;
        if (entry.tool_name !== ("tool_output" as ToolDataEntry["tool_name"])) {
          turn.tool_data = [...turn.tool_data, entry];
          changed = true;
        }
      } else if (
        event.follow_up_actions &&
        Array.isArray(event.follow_up_actions)
      ) {
        turn.follow_up_actions = event.follow_up_actions as string[];
        changed = true;
      } else if (event.main_response_complete === true) {
        turn.loading = false;
        changed = true;
      }

      if (!changed) return;
      addOrUpdateMessage(turnToIMessage(turn, cid));

      if (event.main_response_complete === true) {
        // Close the turn so the next backend event opens a new one. Late-
        // arriving TTS transcriptions can still patch this turn via
        // botTurnsRef (routed by timestamp).
        activeTurnRef.current = null;
      }
    };

    room.registerTextStreamHandler(VOICE_STREAM_TOPIC, handler);
    return () => {
      room.unregisterTextStreamHandler(VOICE_STREAM_TOPIC);
    };
  }, [room, addOrUpdateMessage, openBotTurn]);

  // User transcription effect — runs on every update of LiveKit's transcription
  // list. Builds or extends the current user group and upserts it into the
  // chat store. A new group opened while a bot turn is active is timestamped
  // strictly after the bot's startedAt so the chat sort order is preserved.
  useEffect(() => {
    const cid = conversationIdRef.current;
    if (!cid || !room) return;

    const localIdentity = room.localParticipant.identity;
    const userTrans = transcriptions.filter(
      (t) => t.participantInfo.identity === localIdentity && t.text.trim(),
    );
    if (userTrans.length === 0) return;

    const newTrans = userTrans.filter(
      (t) => !consumedUserTranscriptionIdsRef.current.has(t.streamInfo.id),
    );
    if (newTrans.length === 0) return;

    if (currentUserGroupRef.current === null) {
      const first = newTrans[0];
      const transcriptionTs = first.streamInfo.timestamp || Date.now();
      const activeBotStartedAt =
        activeTurnRef.current?.startedAt.getTime() ?? 0;
      const startedAt = new Date(
        Math.max(transcriptionTs, activeBotStartedAt + 1),
      );
      currentUserGroupRef.current = {
        startStreamId: first.streamInfo.id,
        transcriptionTexts: new Map(),
        startedAt,
      };
    }

    const group = currentUserGroupRef.current;
    for (const t of newTrans) {
      group.transcriptionTexts.set(t.streamInfo.id, t.text);
    }
    if (group.transcriptionTexts.size === 0) return;

    addOrUpdateMessage(userGroupToIMessage(group, cid));
    // conversationId in deps: re-run when the ID arrives so transcriptions
    // buffered during the null window are flushed immediately.
  }, [transcriptions, room, addOrUpdateMessage, conversationId]);
}
