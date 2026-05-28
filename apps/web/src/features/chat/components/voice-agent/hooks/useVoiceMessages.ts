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
  /** TTS-aligned transcription stream ids already applied to this turn. */
  consumedTranscriptionIds: Set<string>;
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
 * Spoken bot text flows through LiveKit's TTS-aligned transcription channel
 * (`useTranscriptions()` filtered to the agent participant) so the bubble
 * fills in lockstep with ElevenLabs audio. UI-only fragments of the backend
 * response (OpenUI markup, structured tags) arrive on the data channel as
 * `event.response_ui` and are appended immediately. Plumbing events
 * (`tool_data`, `follow_up_actions`, `main_response_complete`) keep the
 * immediate-delivery path established in the previous change.
 *
 * Late-arriving TTS transcriptions are routed to the closed turn whose
 * `startedAt` is the latest one still preceding the transcription's
 * timestamp, so a turn that closed early (because `main_response_complete`
 * arrived before TTS finished playing) still gets its spoken text.
 */
export function useVoiceMessages(conversationId: string | null): void {
  const room = useRoomContext();
  const transcriptions = useTranscriptions();
  const addOrUpdateMessage = useChatStore((s) => s.addOrUpdateMessage);

  const activeTurnRef = useRef<VoiceBotTurn | null>(null);
  /** All bot turns this session — used to route late TTS transcriptions to closed turns. */
  const botTurnsRef = useRef<VoiceBotTurn[]>([]);
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
    botTurnsRef.current = [];
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
      consumedTranscriptionIds: new Set(),
    };
    activeTurnRef.current = turn;
    botTurnsRef.current.push(turn);
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
      if (typeof event.response_ui === "string" && event.response_ui) {
        // UI-only fragment from the worker's response split. Append to the
        // bubble's response so the existing OpenUI parser sees it in the same
        // string position as in text mode.
        turn.response += event.response_ui;
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
  }, [transcriptions, room, addOrUpdateMessage]);

  // Bot transcription effect — runs on every update of LiveKit's transcription
  // list. Routes TTS-aligned transcriptions (from the agent participant) to
  // the matching bot turn's response, character-aligned with audio playback.
  useEffect(() => {
    const cid = conversationIdRef.current;
    if (!cid || !room) return;

    const localIdentity = room.localParticipant.identity;
    const botTrans = transcriptions.filter(
      (t) => t.participantInfo.identity !== localIdentity && t.text,
    );
    if (botTrans.length === 0) return;

    let anyChanged = false;
    for (const t of botTrans) {
      const ts = t.streamInfo.timestamp || Date.now();

      // Route to the latest turn whose startedAt is <= timestamp. Falls back
      // to the active turn (or opens one) if no prior turn matches.
      let target: VoiceBotTurn | null = null;
      for (let i = botTurnsRef.current.length - 1; i >= 0; i--) {
        const candidate = botTurnsRef.current[i];
        if (candidate.startedAt.getTime() <= ts) {
          target = candidate;
          break;
        }
      }
      if (!target) {
        target = activeTurnRef.current ?? openBotTurn();
      }

      if (target.consumedTranscriptionIds.has(t.streamInfo.id)) continue;
      target.consumedTranscriptionIds.add(t.streamInfo.id);
      target.response += t.text;
      addOrUpdateMessage(turnToIMessage(target, cid));
      anyChanged = true;
    }

    if (!anyChanged) return;
  }, [transcriptions, room, addOrUpdateMessage, openBotTurn]);
}
