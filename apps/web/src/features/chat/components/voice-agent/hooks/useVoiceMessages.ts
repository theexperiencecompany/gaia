"use client";

import { useRoomContext, useTranscriptions } from "@livekit/components-react";
import type { TextStreamReader } from "livekit-client";
import { useCallback, useEffect, useRef } from "react";
import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import {
  LK_CHAT_TOPIC,
  VOICE_STREAM_TOPIC,
} from "@/features/chat/components/voice-agent/constants";
import type { IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import { useLoadingStore } from "@/stores/loadingStore";

/**
 * OpenUI fences (and the markdown around them) are stripped from the spoken
 * transcript by the agent's TTS sanitiser, so any turn carrying one must
 * render the raw backend response instead. Same marker the bubble renderer
 * keys on (TextBubble / ChatBubbleBot).
 */
const OPENUI_MARKER = ":::openui";

interface VoiceBotTurn {
  localId: string;
  /** Backend response text — fallback when no aligned transcript arrives. */
  response: string;
  /**
   * TTS-aligned transcript per LiveKit segment id. This is what the bubble
   * renders: it streams in sync with the audio actually playing, while
   * `response` runs ahead (it accumulates as text is HANDED to TTS).
   */
  transcriptTexts: Map<string, string>;
  /**
   * Render `response` instead of the transcript. Only flipped once the agent
   * is back to listening with an empty transcript (a turn whose audio never
   * materialized, e.g. TTS failure) — falling back any earlier flashes the
   * full text before the word-by-word transcript replaces it.
   */
  showResponseFallback: boolean;
  tool_data: ToolDataEntry[];
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
  // Render the audio-aligned transcript so the bubble fills as the agent is
  // heard. The backend response text is the fallback for turns whose audio
  // never produced a transcript (e.g. a TTS failure).
  const transcript = Array.from(turn.transcriptTexts.values())
    .map((t) => t.trim())
    .filter(Boolean)
    .join(" ");
  // OpenUI components never reach the spoken transcript (TTS strips the fence),
  // so render the raw response for those turns — otherwise the bubble shows
  // only the prose and the component vanishes. Plain prose keeps the
  // audio-aligned transcript so it stays in sync with the speech.
  const content = turn.response.includes(OPENUI_MARKER)
    ? turn.response
    : transcript || (turn.showResponseFallback ? turn.response : "");
  return {
    id: turn.localId,
    conversationId,
    content,
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

function userGroupToIMessage(
  group: VoiceUserGroup,
  conversationId: string,
): IMessage {
  // Consecutive utterances within one turn (e.g. a pause then more speech) are
  // shown as paragraph breaks in the same bubble.
  const content = Array.from(group.transcriptionTexts.values())
    .map((t) => t.trim())
    .filter(Boolean)
    .join("\n\n");
  return {
    id: group.localId,
    conversationId,
    content,
    role: "user",
    status: "sent",
    createdAt: group.createdAt,
    updatedAt: new Date(),
    optimistic: true,
  };
}

/**
 * Subscribes to LiveKit transcriptions (user speech, in real time) and the
 * agent's bot stream, writing both into `chatStore`. Returns `sendUserTurn` for
 * injecting a typed/clicked message (e.g. a follow-up suggestion) as a new voice
 * turn.
 *
 * Ordering is kept correct by two devices: (1) a strictly-increasing timestamp
 * stamped once when each user group / bot turn is FIRST created, and (2) mutual
 * turn-closing — opening a bot turn closes the open user group, and a new user
 * utterance closes the active bot turn. This stops different turns' text, tools,
 * and follow-ups from stacking into one bubble, and keeps user/bot order stable
 * even with `preemptive_generation` on the agent.
 */
export function useVoiceMessages(
  conversationId: string | null,
  agentState: string,
): { sendUserTurn: (text: string) => Promise<void> } {
  const room = useRoomContext();
  const transcriptions = useTranscriptions();
  const addOrUpdateMessage = useChatStore((s) => s.addOrUpdateMessage);

  const activeTurnRef = useRef<VoiceBotTurn | null>(null);
  const currentUserGroupRef = useRef<VoiceUserGroup | null>(null);
  /** Transcription stream ids already flushed as part of a closed user group. */
  const consumedUserTranscriptionIdsRef = useRef<Set<string>>(new Set());
  /** Agent transcription ids belonging to already-closed bot turns. */
  const consumedBotTranscriptionIdsRef = useRef<Set<string>>(new Set());
  const botTurnIndexRef = useRef(0);
  const userGroupIndexRef = useRef(0);
  /** Last issued message timestamp (ms) — kept strictly increasing. */
  const seqClockRef = useRef(0);
  /** Bot-stream events that arrived before the conversation id was known. */
  const pendingEventsRef = useRef<Record<string, unknown>[]>([]);
  /**
   * Whether the current turn has produced an audible bot transcript yet. Once
   * true the thinking indicator stays cleared until the NEXT user turn — so
   * the backend re-entering "thinking" to generate follow-ups (after the
   * reply is already on screen) can't resurrect it.
   */
  const botTokenSeenThisTurnRef = useRef(false);
  /**
   * Whether the current turn's USER message has rendered. The agent can enter
   * "thinking" before the user's transcript reaches the frontend — showing
   * the indicator first and the user's words after looks glitchy, so the
   * indicator only shows once the bubble exists.
   */
  const userMessageRenderedRef = useRef(false);

  // Stash the latest conversationId in a ref so the bot-stream handler closure
  // (registered once) always reads the current value.
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;

  // Reset internal state on remount (new voice session).
  useEffect(() => {
    activeTurnRef.current = null;
    currentUserGroupRef.current = null;
    consumedUserTranscriptionIdsRef.current = new Set();
    consumedBotTranscriptionIdsRef.current = new Set();
    botTurnIndexRef.current = 0;
    userGroupIndexRef.current = 0;
    seqClockRef.current = 0;
    pendingEventsRef.current = [];
    botTokenSeenThisTurnRef.current = false;
    userMessageRenderedRef.current = false;
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
    for (const id of group.transcriptionTexts.keys()) {
      consumedUserTranscriptionIdsRef.current.add(id);
    }
    currentUserGroupRef.current = null;
  }, []);

  // Close the active bot turn: mark its transcript segment ids consumed so a
  // late update (e.g. the tail of interrupted speech) can't reopen it.
  const closeBotTurn = useCallback(() => {
    const turn = activeTurnRef.current;
    if (!turn) return;
    for (const id of turn.transcriptTexts.keys()) {
      consumedBotTranscriptionIdsRef.current.add(id);
    }
    activeTurnRef.current = null;
  }, []);

  // Open a new bot turn. Closes the open user group. The thinking indicator
  // intentionally stays on — backend tokens arrive seconds before any audio,
  // so it clears on the first audible transcript segment instead.
  const openBotTurn = useCallback((): VoiceBotTurn => {
    closeUserGroup();
    botTurnIndexRef.current += 1;
    const sid = room?.name || "voice";
    const turn: VoiceBotTurn = {
      localId: `voice-bot-${sid}-${botTurnIndexRef.current}`,
      response: "",
      transcriptTexts: new Map(),
      showResponseFallback: false,
      tool_data: [],
      follow_up_actions: [],
      loading: true,
      createdAt: nextCreatedAt(),
    };
    activeTurnRef.current = turn;
    return turn;
  }, [room, nextCreatedAt, closeUserGroup]);

  const processBotEvent = useCallback(
    (event: Record<string, unknown>, cid: string) => {
      // Ignore plumbing that doesn't render in the bubble. tool_output is
      // backend-internal; conversation_id/description are handled by the
      // dedicated text-stream handlers in VoiceControlBarContainer; user_message
      // is legacy (user bubbles now come from live transcriptions).
      if (
        "tool_output" in event ||
        "conversation_id" in event ||
        "conversation_description" in event ||
        "user_message" in event
      ) {
        return;
      }

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
        // Response done, but keep the turn active: the backend emits
        // follow_up_actions AFTER this marker and they must attach to the same
        // bubble. The turn closes when the next user utterance starts.
        turn.loading = false;
        changed = true;
      }

      if (!changed) return;
      // Don't render a visually-empty bubble: response text accumulates
      // silently until the audio (transcript) starts, or cards/follow-ups
      // give the bubble something to show.
      const hasVisibleContent =
        turn.transcriptTexts.size > 0 ||
        turn.tool_data.length > 0 ||
        turn.follow_up_actions.length > 0 ||
        turn.showResponseFallback ||
        // A pure-OpenUI turn has no spoken prose, so its transcript stays
        // empty — show the bubble as soon as the fence arrives in the response.
        turn.response.includes(OPENUI_MARKER);
      if (!hasVisibleContent) return;
      addOrUpdateMessage(turnToIMessage(turn, cid));
    },
    [addOrUpdateMessage, openBotTurn],
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
  }, [room, processBotEvent]);

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
    if (!cid || !room) return;

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
      closeBotTurn();
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
    addOrUpdateMessage(userGroupToIMessage(group, cid));
    userMessageRenderedRef.current = true;
  }, [
    transcriptions,
    room,
    addOrUpdateMessage,
    conversationId,
    nextCreatedAt,
    closeBotTurn,
  ]);

  // Agent's TTS-aligned transcript → live bot bubble. With
  // `use_tts_aligned_transcript` on the agent, these segments stream in sync
  // with the audio actually playing — unlike the backend response chunks,
  // which accumulate as fast as the LLM generates.
  useEffect(() => {
    const cid = conversationIdRef.current;
    if (!cid || !room) return;

    const localIdentity = room.localParticipant.identity;
    const agentTrans = transcriptions.filter(
      (t) => t.participantInfo.identity !== localIdentity && t.text.trim(),
    );
    if (agentTrans.length === 0) return;

    let turn = activeTurnRef.current;
    let changed = false;
    for (const t of agentTrans) {
      const id = t.streamInfo.id;
      if (consumedBotTranscriptionIdsRef.current.has(id)) continue;
      // A segment with no open turn (e.g. the session greeting) opens one.
      turn = turn ?? openBotTurn();
      turn.transcriptTexts.set(id, t.text);
      changed = true;
    }
    if (changed && turn) {
      // First audible words of this turn — the thinking indicator's job is
      // done, and it stays cleared for the rest of the turn.
      botTokenSeenThisTurnRef.current = true;
      useLoadingStore.getState().setLoading(false);
      addOrUpdateMessage(turnToIMessage(turn, cid));
    }
  }, [transcriptions, room, addOrUpdateMessage, openBotTurn]);

  // Send a typed/clicked message (e.g. a follow-up suggestion) as a new voice
  // turn. There is no STT transcription for an injected message, so this mirrors
  // what the transcription path does for a spoken turn: render the user's text
  // immediately, close the active bot turn so the reply opens a FRESH bubble
  // (otherwise the next reply clubs onto the previous turn), re-arm the thinking
  // indicator, then publish the text to the agent over LiveKit.
  const sendUserTurn = useCallback(
    async (text: string): Promise<void> => {
      const trimmed = text.trim();
      const cid = conversationIdRef.current;
      if (!trimmed || !room || !cid) return;

      closeUserGroup();
      closeBotTurn();
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
      addOrUpdateMessage(userGroupToIMessage(group, cid));
      userMessageRenderedRef.current = true;

      await room.localParticipant.sendText(trimmed, { topic: LK_CHAT_TOPIC });
    },
    [room, addOrUpdateMessage, nextCreatedAt, closeUserGroup, closeBotTurn],
  );

  // Thinking-indicator lifecycle. Armed once per turn: show it when the user's
  // turn ends and the agent starts processing (`thinking`), but only until
  // this turn's first audible transcript — `botTokenSeenThisTurnRef` (reset
  // when a new user turn starts) suppresses the LATER "thinking" the backend
  // enters while generating follow-ups. Skipped when the user's own bubble
  // hasn't rendered yet (the STT transcript can lag the agent by a beat) —
  // an indicator above nothing reads as a glitch. `listening` clears it as a
  // safety net.
  useEffect(() => {
    if (agentState === "thinking" && !botTokenSeenThisTurnRef.current) {
      if (userMessageRenderedRef.current) {
        useLoadingStore.getState().setLoading(true);
      }
    } else if (agentState === "listening") {
      useLoadingStore.getState().setLoading(false);

      // Turn finished with audio never materializing (e.g. TTS failure):
      // fall back to the backend response text so the reply isn't lost.
      // Doing this any earlier flashes the full text before the streaming
      // transcript replaces it.
      const turn = activeTurnRef.current;
      const cid = conversationIdRef.current;
      if (
        turn &&
        cid &&
        !turn.loading &&
        turn.transcriptTexts.size === 0 &&
        turn.response &&
        !turn.showResponseFallback
      ) {
        turn.showResponseFallback = true;
        addOrUpdateMessage(turnToIMessage(turn, cid));
      }
    }
  }, [agentState, addOrUpdateMessage]);

  // Clear the indicator when leaving voice mode.
  useEffect(() => () => useLoadingStore.getState().setLoading(false), []);

  return { sendUserTurn };
}
