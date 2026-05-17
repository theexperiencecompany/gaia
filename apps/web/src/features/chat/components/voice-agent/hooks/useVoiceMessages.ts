"use client";

import { useRoomContext, useTranscriptions } from "@livekit/components-react";
import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";
import type { TextStreamReader } from "livekit-client";
import { useEffect, useRef } from "react";
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
 * User transcriptions arriving between bot turns are grouped into a single
 * message whose content is joined with `<NEW_MESSAGE_BREAK>` — `splitMessageByBreaks`
 * in the renderer turns those into paragraph breaks within one bubble.
 *
 * Bot turns close the active user group so the next transcription starts a
 * fresh one. Because the bot turn's `createdAt` is strictly later than the
 * user group's, the chat store's createdAt-based sort keeps the bot bubble
 * below the user bubble — even when preemptive_generation makes the bot's
 * first event arrive before the user's STT finalisation.
 */
export function useVoiceMessages(conversationId: string | null): void {
  const room = useRoomContext();
  const transcriptions = useTranscriptions();
  const addOrUpdateMessage = useChatStore((s) => s.addOrUpdateMessage);

  const activeTurnRef = useRef<VoiceBotTurn | null>(null);
  const currentUserGroupRef = useRef<VoiceUserGroup | null>(null);
  /** Stream ids that have been flushed as part of a closed user group. */
  const consumedTranscriptionIdsRef = useRef<Set<string>>(new Set());
  const botTurnIndexRef = useRef(0);

  // Stash the latest conversationId in a ref so the bot-stream handler
  // closure (registered once with [room] deps) always sees the current value.
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;

  // Reset internal state on remount (new voice session).
  useEffect(() => {
    activeTurnRef.current = null;
    currentUserGroupRef.current = null;
    consumedTranscriptionIdsRef.current = new Set();
    botTurnIndexRef.current = 0;
  }, []);

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

      // Ignore plumbing events that don't render
      if (
        "tool_output" in event ||
        "conversation_id" in event ||
        "conversation_description" in event
      ) {
        return;
      }

      const cid = conversationIdRef.current;
      if (!cid) return; // no conversation yet → nowhere to write

      // First content-bearing event of a new bot turn: close the active user
      // group (mark its transcription ids as consumed) and create the turn.
      if (activeTurnRef.current === null) {
        const group = currentUserGroupRef.current;
        if (group) {
          for (const id of group.transcriptionTexts.keys()) {
            consumedTranscriptionIdsRef.current.add(id);
          }
          currentUserGroupRef.current = null;
        }
        botTurnIndexRef.current += 1;
        const idx = botTurnIndexRef.current;
        const sid = room.name || "voice";
        activeTurnRef.current = {
          localId: `voice-bot-${sid}-${idx}-${Date.now()}`,
          response: "",
          tool_data: [],
          follow_up_actions: [],
          loading: true,
          startedAt: new Date(),
        };
      }

      const turn = activeTurnRef.current;
      if (!turn) return;

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
        activeTurnRef.current = null;
      }
    };

    room.registerTextStreamHandler(VOICE_STREAM_TOPIC, handler);
    return () => {
      room.unregisterTextStreamHandler(VOICE_STREAM_TOPIC);
    };
  }, [room, addOrUpdateMessage]);

  // Transcription effect — runs on every update of LiveKit's transcription
  // list. Builds or extends the current user group and upserts it into the
  // chat store.
  useEffect(() => {
    const cid = conversationIdRef.current;
    if (!cid || !room) return;

    const localIdentity = room.localParticipant.identity;
    const userTrans = transcriptions.filter(
      (t) => t.participantInfo.identity === localIdentity && t.text.trim(),
    );
    if (userTrans.length === 0) return;

    // Filter out transcriptions already consumed by a closed group.
    const newTrans = userTrans.filter(
      (t) => !consumedTranscriptionIdsRef.current.has(t.streamInfo.id),
    );
    if (newTrans.length === 0) return;

    // While a bot turn is in flight, do not open a new user group.
    // The next transcription that arrives after the turn closes will open one.
    if (activeTurnRef.current !== null) return;

    // Open a new group if needed.
    if (currentUserGroupRef.current === null) {
      const first = newTrans[0];
      currentUserGroupRef.current = {
        startStreamId: first.streamInfo.id,
        transcriptionTexts: new Map(),
        startedAt: new Date(first.streamInfo.timestamp || Date.now()),
      };
    }

    const group = currentUserGroupRef.current;
    for (const t of newTrans) {
      group.transcriptionTexts.set(t.streamInfo.id, t.text);
    }
    if (group.transcriptionTexts.size === 0) return;

    addOrUpdateMessage(userGroupToIMessage(group, cid));
  }, [transcriptions, room, addOrUpdateMessage]);
}
