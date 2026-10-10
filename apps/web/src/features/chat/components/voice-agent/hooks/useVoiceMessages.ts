"use client";

import { useRoomContext, useTranscriptions } from "@livekit/components-react";
import type { TextStreamReader } from "livekit-client";
import { useCallback, useEffect, useRef } from "react";
import type { TypedToolDataEntry } from "@/config/registries/toolRegistry";
import {
  LK_CHAT_TOPIC,
  VOICE_STREAM_TOPIC,
} from "@/features/chat/components/voice-agent/constants";
import { readToolDataLoadingHints } from "@/features/chat/utils/loadingHints";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import type { IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import { useStreamStore } from "@/stores/streamStore";
import { useVoiceModeActions } from "@/stores/voiceModeStore";

interface VoiceBotTurn {
  localId: string;
  response: string;
  tool_data: TypedToolDataEntry[];
  follow_up_actions: string[];
  loading: boolean;
  createdAt: Date;
}

interface VoiceUserGroup {
  localId: string;
  /** Per-stream text keyed by LiveKit transcription stream id. */
  transcriptionTexts: Map<string, string>;
  createdAt: Date;
}

function turnToIMessage(turn: VoiceBotTurn, conversationId: string): IMessage {
  return {
    id: turn.localId,
    conversationId,
    content: turn.response,
    role: "assistant",
    status: turn.loading ? "sending" : "sent",
    createdAt: turn.createdAt,
    updatedAt: new Date(),
    tool_data: turn.tool_data.length > 0 ? turn.tool_data : null,
    follow_up_actions:
      turn.follow_up_actions.length > 0 ? turn.follow_up_actions : null,
    optimistic: true,
  };
}

// Plumbing keys, not bubble content: conversation_id/description have
// dedicated text-stream handlers in VoiceControlBarContainer; user_message is
// legacy (user bubbles now come from live transcriptions).
const NON_RENDERING_EVENT_KEYS = [
  "tool_output",
  "conversation_id",
  "conversation_description",
  "user_message",
] as const;

function isNonRenderingEvent(event: Record<string, unknown>): boolean {
  return NON_RENDERING_EVENT_KEYS.some((key) => key in event);
}

// Appends a tool_data entry and surfaces the matching loading line (same
// hints/store/LoadingIndicator as text mode); re-arms the spinner if a bot
// token already cleared it. Skips internal tool_output entries.
function appendToolDataEntry(
  turn: VoiceBotTurn,
  entry: TypedToolDataEntry,
): boolean {
  if (entry.tool_name === ("tool_output" as TypedToolDataEntry["tool_name"])) {
    return false;
  }
  turn.tool_data = [...turn.tool_data, entry];
  const hints = readToolDataLoadingHints((entry as { data?: unknown }).data);
  if (hints) {
    const { message, ...toolInfo } = hints;
    useStreamStore.getState().setAuxLoading(true, message, toolInfo);
  }
  return true;
}

/**
 * Join transcription texts into bubble content in one pass: trim each
 * utterance, drop the empty ones, paragraph break between utterances.
 */
function joinTranscriptionTexts(texts: Iterable<string>): string {
  return Array.from(texts)
    .flatMap((text) => {
      const trimmed = text.trim();
      return trimmed ? [trimmed] : [];
    })
    .join("\n\n");
}

function userGroupToIMessage(
  group: VoiceUserGroup,
  conversationId: string,
  // While the user is still speaking the transcript grows — mark it "sending" so
  // the bubble animates the incoming words; "sent" once the group is finalized.
  streaming: boolean,
): IMessage {
  // Consecutive utterances within one turn (e.g. a pause then more speech) are
  // shown as paragraph breaks in the same bubble.
  const content = joinTranscriptionTexts(group.transcriptionTexts.values());
  return {
    id: group.localId,
    conversationId,
    content,
    role: "user",
    status: streaming ? "sending" : "sent",
    createdAt: group.createdAt,
    updatedAt: new Date(),
    optimistic: true,
  };
}

/**
 * Subscribe to LiveKit transcriptions and the bot stream, writing both into `chatStore`.
 *
 * Ordering relies on a strictly-increasing creation timestamp per turn plus mutual
 * turn-closing (opening a bot turn closes the user group and vice versa), which
 * keeps turns from stacking even under `preemptive_generation`.
 */
export function useVoiceMessages(
  conversationId: string | null,
  agentState: string,
): { sendUserTurn: (text: string) => Promise<void> } {
  const room = useRoomContext();
  const transcriptions = useTranscriptions();
  const addOrUpdateMessage = useChatStore((s) => s.addOrUpdateMessage);
  const { setDiscoveredConversationId } = useVoiceModeActions();

  const activeTurnRef = useRef<VoiceBotTurn | null>(null);
  const currentUserGroupRef = useRef<VoiceUserGroup | null>(null);
  /** Transcription stream ids already flushed as part of a closed user group. */
  const consumedUserTranscriptionIdsRef = useRef<Set<string>>(new Set());
  const botTurnIndexRef = useRef(0);
  const userGroupIndexRef = useRef(0);
  /** Last issued message timestamp (ms) — kept strictly increasing. */
  const seqClockRef = useRef(0);
  /** Bot-stream events that arrived before the conversation id was known. */
  const pendingEventsRef = useRef<Record<string, unknown>[]>([]);
  /**
   * Whether the current turn has produced a bot token yet. Once true the
   * thinking indicator stays cleared until the NEXT user turn — so the backend
   * re-entering "thinking" to generate follow-ups (after the reply is already
   * on screen) can't resurrect it.
   */
  const botTokenSeenThisTurnRef = useRef(false);

  // Stash the latest conversationId in a ref so the bot-stream handler closure
  // (registered once) always reads the current value.
  const conversationIdRef = useRef(conversationId);
  useEffect(() => {
    conversationIdRef.current = conversationId;
  });

  // Reset internal state on remount (new voice session).
  useEffect(() => {
    activeTurnRef.current = null;
    currentUserGroupRef.current = null;
    consumedUserTranscriptionIdsRef.current = new Set();
    botTurnIndexRef.current = 0;
    userGroupIndexRef.current = 0;
    seqClockRef.current = 0;
    pendingEventsRef.current = [];
    botTokenSeenThisTurnRef.current = false;
  }, []);

  // Strictly-increasing timestamp so the chatStore `createdAt` sort matches
  // creation order even when messages land in the same millisecond.
  const nextCreatedAt = useCallback((): Date => {
    const t = Math.max(Date.now(), seqClockRef.current + 1);
    seqClockRef.current = t;
    return new Date(t);
  }, []);

  // Close the current user group: mark its transcription ids consumed so the
  // next utterance opens a fresh group/bubble.
  const closeUserGroup = useCallback(() => {
    const group = currentUserGroupRef.current;
    if (!group) return;
    // Finalize the bubble: re-emit the group as "sent" so it stops animating
    // (it was last written as "sending" while the user was still speaking).
    const cid = conversationIdRef.current;
    if (cid && group.transcriptionTexts.size > 0) {
      addOrUpdateMessage(userGroupToIMessage(group, cid, false));
    }
    for (const id of group.transcriptionTexts.keys()) {
      consumedUserTranscriptionIdsRef.current.add(id);
    }
    currentUserGroupRef.current = null;
  }, [addOrUpdateMessage]);

  // Open a new bot turn. Closes the open user group and clears the thinking
  // indicator (this turn's first token has arrived).
  const openBotTurn = useCallback((): VoiceBotTurn => {
    closeUserGroup();
    botTurnIndexRef.current += 1;
    const sid = room?.name || "voice";
    const turn: VoiceBotTurn = {
      localId: `voice-bot-${sid}-${botTurnIndexRef.current}`,
      response: "",
      tool_data: [],
      follow_up_actions: [],
      loading: true,
      createdAt: nextCreatedAt(),
    };
    activeTurnRef.current = turn;
    // This turn's first token has arrived — clear the thinking indicator and
    // keep it cleared for the rest of the turn.
    botTokenSeenThisTurnRef.current = true;
    useStreamStore.getState().setAuxLoading(false);
    return turn;
  }, [room, nextCreatedAt, closeUserGroup]);

  const processBotEvent = useCallback(
    (event: Record<string, unknown>, cid: string) => {
      if (isNonRenderingEvent(event)) return;

      // A delegated executor's final answer ({response, message_id}) renders as
      // its own bubble keyed by message_id, not folded into the comms-ack turn.
      // The WebSocket conversation.new_message carries the same id and reconciles in place.
      const answerId = event.message_id;
      if (
        typeof answerId === "string" &&
        answerId &&
        typeof event.response === "string" &&
        event.response
      ) {
        addOrUpdateMessage({
          id: answerId,
          conversationId: cid,
          content: event.response,
          role: "assistant",
          status: "sent",
          createdAt: nextCreatedAt(),
          updatedAt: new Date(),
          messageId: answerId,
          tool_data: null,
          follow_up_actions: null,
          optimistic: true,
        });
        return;
      }

      const turn = activeTurnRef.current ?? openBotTurn();

      let changed = false;
      if (typeof event.response === "string" && event.response) {
        turn.response += event.response;
        changed = true;
      } else if (event.tool_data && typeof event.tool_data === "object") {
        changed = appendToolDataEntry(
          turn,
          event.tool_data as TypedToolDataEntry,
        );
      } else if (
        event.follow_up_actions &&
        Array.isArray(event.follow_up_actions)
      ) {
        turn.follow_up_actions = event.follow_up_actions as string[];
        changed = true;
      } else if (event.main_response_complete === true) {
        // Response done, but keep the turn active: the backend emits
        // follow_up_actions AFTER this marker and they must attach to the same
        // bubble. The turn closes when the next user utterance starts.
        turn.loading = false;
        // Drop any per-tool loading label so it doesn't linger past the reply.
        useStreamStore.getState().setAuxLoading(false);
        changed = true;
      }

      if (!changed) return;
      addOrUpdateMessage(turnToIMessage(turn, cid));
    },
    [addOrUpdateMessage, openBotTurn, nextCreatedAt],
  );

  // Bot data-channel handler — runs on every event the agent emits.
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

      // Adopt the conversation id from this in-band event (the bot stream provably
      // delivers) rather than only the separate `conversation-id` text stream,
      // whose single send drops if its handler isn't registered yet — stranding the id.
      const convId = event.conversation_id;
      if (typeof convId === "string" && convId) {
        setDiscoveredConversationId(convId);
      }

      const cid = conversationIdRef.current;
      if (!cid) {
        // Buffer until the backend conversation id arrives, then flush in order.
        pendingEventsRef.current.push(event);
        return;
      }
      processBotEvent(event, cid);
    };

    room.registerTextStreamHandler(VOICE_STREAM_TOPIC, handler);
    return () => {
      room.unregisterTextStreamHandler(VOICE_STREAM_TOPIC);
    };
  }, [room, processBotEvent, setDiscoveredConversationId]);

  // Flush buffered bot events once the conversation id is known.
  useEffect(() => {
    if (!conversationId || pendingEventsRef.current.length === 0) return;
    const buffered = pendingEventsRef.current;
    pendingEventsRef.current = [];
    for (const event of buffered) {
      processBotEvent(event, conversationId);
    }
  }, [conversationId, processBotEvent]);

  // Live user transcriptions → user bubbles. Re-runs on every transcription
  // update (so the bubble fills in real time) and when the conversation id
  // arrives (so the first turn isn't dropped during the null-id window).
  useEffect(() => {
    const cid = conversationIdRef.current;
    if (!room) return;

    const localIdentity = room.localParticipant.identity;
    const userTrans = transcriptions.filter(
      (t) => t.participantInfo.identity === localIdentity && t.text.trim(),
    );
    if (userTrans.length === 0) return;

    const fresh = userTrans.filter(
      (t) => !consumedUserTranscriptionIdsRef.current.has(t.streamInfo.id),
    );
    if (fresh.length === 0) return;

    // First fresh transcription of a new utterance opens a group — and closes
    // the active bot turn so the previous reply/tools/followups don't merge
    // into the next turn.
    if (currentUserGroupRef.current === null) {
      trackEvent(ANALYTICS_EVENTS.VOICE_TRANSCRIPTION_RECEIVED, {
        conversation_id: cid,
      });
      activeTurnRef.current = null;
      // New user turn — re-arm the thinking indicator for the upcoming reply.
      botTokenSeenThisTurnRef.current = false;
      userGroupIndexRef.current += 1;
      const sid = room.name || "voice";
      currentUserGroupRef.current = {
        localId: `voice-user-${sid}-${userGroupIndexRef.current}`,
        transcriptionTexts: new Map(),
        createdAt: nextCreatedAt(),
      };
    }

    const group = currentUserGroupRef.current;
    for (const t of fresh) {
      group.transcriptionTexts.set(t.streamInfo.id, t.text);
    }
    if (cid) {
      addOrUpdateMessage(userGroupToIMessage(group, cid, true));
    } else {
      // No backend conversation id yet: show the utterance via the same optimistic
      // slot text mode uses (useConversation, while activeConversationId is null).
      // The effect below re-runs and clears the slot once the id arrives.
      useChatStore.getState().setOptimisticMessage({
        id: group.localId,
        conversationId: null,
        role: "user",
        content: joinTranscriptionTexts(group.transcriptionTexts.values()),
        createdAt: group.createdAt,
      });
    }
  }, [transcriptions, room, addOrUpdateMessage, conversationId, nextCreatedAt]);

  // Promotes the optimistic first turn once the conversation id arrives: activates
  // the conversation and drops the slot. Fires on the id, not the title — the
  // description arrives ~1-2s later and would leave the reply hidden until then.
  useEffect(() => {
    if (!conversationId) return;
    const store = useChatStore.getState();
    store.setActiveConversationId(conversationId);
    store.clearOptimisticMessage();
  }, [conversationId]);

  // Sends a typed/clicked message as a new voice turn: no STT exists for
  // injected text, so mirror the spoken-turn path — render immediately, close
  // the active bot turn (else replies club together), then publish over LiveKit.
  const sendUserTurn = useCallback(
    async (text: string): Promise<void> => {
      const trimmed = text.trim();
      const cid = conversationIdRef.current;
      if (!trimmed || !room || !cid) return;

      closeUserGroup();
      activeTurnRef.current = null;
      botTokenSeenThisTurnRef.current = false;
      userGroupIndexRef.current += 1;
      const sid = room.name || "voice";
      const group: VoiceUserGroup = {
        localId: `voice-user-${sid}-${userGroupIndexRef.current}`,
        transcriptionTexts: new Map([
          [`injected-${userGroupIndexRef.current}`, trimmed],
        ]),
        createdAt: nextCreatedAt(),
      };
      // Injected text is complete, not a live transcript — render it settled.
      addOrUpdateMessage(userGroupToIMessage(group, cid, false));

      await room.localParticipant.sendText(trimmed, { topic: LK_CHAT_TOPIC });
    },
    [room, addOrUpdateMessage, nextCreatedAt, closeUserGroup],
  );

  // Shows the thinking indicator once per turn until the first bot token —
  // botTokenSeenThisTurnRef suppresses the backend's LATER "thinking" during
  // follow-up generation (which kept the indicator on); `listening` clears it too.
  useEffect(() => {
    if (agentState === "thinking" && !botTokenSeenThisTurnRef.current) {
      useStreamStore.getState().setAuxLoading(true);
    } else if (agentState === "listening") {
      useStreamStore.getState().setAuxLoading(false);
    }
  }, [agentState]);

  // Clear the indicator when leaving voice mode.
  useEffect(() => () => useStreamStore.getState().setAuxLoading(false), []);

  return { sendUserTurn };
}
