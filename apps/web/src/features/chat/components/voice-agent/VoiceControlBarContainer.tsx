"use client";

import {
  RoomAudioRenderer,
  RoomContext,
  StartAudio,
  useLocalParticipant,
  useRoomContext,
  useVoiceAssistant,
} from "@livekit/components-react";
import type { TextStreamReader } from "livekit-client";
import { Room } from "livekit-client";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { AgentControlBar } from "@/features/chat/components/voice-agent/agent-control-bar";
import useConnectionDetails from "@/features/chat/components/voice-agent/hooks/useConnectionDetails";
import { useVoiceMessages } from "@/features/chat/components/voice-agent/hooks/useVoiceMessages";
import { useVoiceSpectrum } from "@/features/chat/components/voice-agent/hooks/useVoiceSpectrum";
import { VoiceConnectionStatus } from "@/features/chat/components/voice-agent/VoiceConnectionStatus";
import {
  useVoiceSession,
  VoiceSessionProvider,
  type VoiceSessionValue,
} from "@/features/chat/components/voice-agent/VoiceSessionContext";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { db, type IConversation } from "@/lib/db/chatDb";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/stores/chatStore";
import {
  useDiscoveredConversationId,
  useVoiceModeActions,
} from "@/stores/voiceModeStore";

const SESSION_READY_TIMEOUT_MS = 10_000;

/**
 * Delay between muting the mic and freezing the gradient's draw loop —
 * matches the spectrum hook's settle window so the wave has glided down to
 * flat before the canvas freezes on its final frame.
 */
const MUTE_ANIMATION_FREEZE_MS = 700;

interface VoiceControlBarContainerProps {
  /** Rendered inside the session provider so they can read `useVoiceSession()`. */
  children?: React.ReactNode;
}

/**
 * Subscribes to the `conversation-id` and `conversation-description` text
 * streams the voice worker emits on the LiveKit room. Re-registers on
 * reconnect.
 */
function useRoomConversationStreams({
  onConversationId,
  onConversationDescription,
}: {
  onConversationId: (id: string) => void;
  onConversationDescription: (description: string) => void;
}) {
  const room = useRoomContext();

  useEffect(() => {
    if (!room) return;

    const idHandler = async (reader: TextStreamReader) => {
      try {
        const text = await reader.readAll();
        if (text) onConversationId(text);
      } catch {
        // ignore
      }
    };
    const descHandler = async (reader: TextStreamReader) => {
      try {
        const text = await reader.readAll();
        if (text) onConversationDescription(text);
      } catch {
        // ignore
      }
    };

    const register = () => {
      try {
        room.unregisterTextStreamHandler("conversation-id");
        room.unregisterTextStreamHandler("conversation-description");
      } catch {
        // ignore
      }
      room.registerTextStreamHandler("conversation-id", idHandler);
      room.registerTextStreamHandler("conversation-description", descHandler);
    };

    room.on("connected", register);
    if (room.state === "connected") register();

    return () => {
      room.off("connected", register);
      try {
        room.unregisterTextStreamHandler("conversation-id");
        room.unregisterTextStreamHandler("conversation-description");
      } catch {
        // ignore
      }
    };
  }, [room, onConversationId, onConversationDescription]);
}

/**
 * Owns the audio renderer, side effects (loading store, auto-redirect,
 * connection toast), and populates the VoiceSession context. The actual
 * UI for the bar is rendered by `<VoiceControlBarSlot/>` consumers below
 * the provider so it can slot into the chat layout's bottom bar.
 */
function VoiceSessionInner({ children }: { children?: React.ReactNode }) {
  const { id: convoIdParam } = useParams<{ id: string }>();
  const { state: agentState, audioTrack: agentAudioTrack } =
    useVoiceAssistant();
  const room = useRoomContext();

  const storeDiscoveredId = useDiscoveredConversationId();
  const { setDiscoveredConversationId } = useVoiceModeActions();
  const [conversationDescription, setConversationDescription] = useState<
    string | null
  >(null);

  const discoveredConversationId = storeDiscoveredId ?? convoIdParam ?? null;
  const conversationId = discoveredConversationId;

  // useVoiceMessages owns the thinking-indicator lifecycle: it's the only place
  // that knows when a turn's first token arrives and when a new user turn
  // starts. Driving it off agentState alone surfaced the indicator AFTER the
  // reply, because the backend re-enters "thinking" while it generates
  // follow-up actions (stream open, no TTS).
  const { sendUserTurn } = useVoiceMessages(conversationId, agentState);

  useRoomConversationStreams({
    onConversationId: setDiscoveredConversationId,
    onConversationDescription: setConversationDescription,
  });

  // Mount /c/:id once the backend conversation id is known, WITHOUT triggering
  // a Next.js navigation. `router.replace` would remount ChatPage (/c and
  // /c/:id are distinct App Router segments), tearing down the LiveKit Room
  // mid-session. `window.history.replaceState` updates the URL in place.
  //
  // Read the live `window.location.pathname` (NOT usePathname/useParams): Next
  // patches history so usePathname updates after replaceState while useParams
  // does not, which made the old effect re-fire and append a second segment
  // (/c/id1/c/id2). We compare the real last URL segment and strip a trailing
  // `/c` OR `/c/<id>` to recover the locale prefix, so the id is mounted once.
  const lastAppliedConvoIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!discoveredConversationId || typeof window === "undefined") return;
    if (lastAppliedConvoIdRef.current === discoveredConversationId) return;

    const path = window.location.pathname;
    const segments = path.split("/").filter(Boolean);
    const lastSegment = segments[segments.length - 1];
    if (lastSegment === discoveredConversationId) {
      lastAppliedConvoIdRef.current = discoveredConversationId;
      return;
    }

    const localePrefix = path.replace(/\/c(\/[^/]+)?$/, "");
    const newUrl = `${localePrefix}/c/${discoveredConversationId}`;
    window.history.replaceState(window.history.state, "", newUrl);
    lastAppliedConvoIdRef.current = discoveredConversationId;
  }, [discoveredConversationId]);

  const remoteTrack = useMemo(
    () => agentAudioTrack?.publication?.track?.mediaStreamTrack ?? null,
    [agentAudioTrack],
  );
  const isConnecting =
    agentState === "connecting" || room?.state !== "connected";
  // "thinking" rides the loading shimmer too — a dead-flat wave while the
  // backend works reads as a hang; the gentle vibration signals activity.
  const spectrumSource =
    isConnecting || agentState === "thinking"
      ? "loading"
      : agentState === "speaking" && remoteTrack
        ? "agent-track"
        : agentState === "listening"
          ? "mic"
          : "idle";
  // The REAL mic state — LiveKit's track toggle in the control bar — drives
  // the spectrum's mute, not a hook-local flag. Muted mic ⇒ wave settles
  // flat and sampling pauses; the agent's own speech still animates.
  const { isMicrophoneEnabled } = useLocalParticipant();
  const micMuted = !isMicrophoneEnabled;
  const voice = useVoiceSpectrum({
    source: spectrumSource,
    remoteTrack,
    muted: micMuted,
  });

  // Freeze the gradient's GL draw loop once the muted wave has settled flat.
  // Only mic/idle frames freeze — agent speech (agent-track) and activity
  // shimmer (loading: connecting or thinking) keep animating while muted.
  const [animationPaused, setAnimationPaused] = useState(false);
  useEffect(() => {
    const shouldFreeze =
      micMuted && (spectrumSource === "mic" || spectrumSource === "idle");
    if (!shouldFreeze) {
      setAnimationPaused(false);
      return;
    }
    const timer = setTimeout(
      () => setAnimationPaused(true),
      MUTE_ANIMATION_FREEZE_MS,
    );
    return () => clearTimeout(timer);
  }, [micMuted, spectrumSource]);

  // When a loading-shimmer phase (connecting OR thinking) ends, fade the
  // procedural jitter to zero over ~300ms before the spectrum source switches
  // to mic/agent-track, so the wave settles smoothly instead of snapping.
  const wasLoadingRef = useRef(spectrumSource === "loading");
  useEffect(() => {
    const isLoading = spectrumSource === "loading";
    if (wasLoadingRef.current && !isLoading) {
      voice.decayLoading();
    }
    wasLoadingRef.current = isLoading;
  }, [spectrumSource, voice.decayLoading]);

  const startedRef = useRef(false);
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    voice.start();
  }, [voice.start]);

  useEffect(() => {
    if (!discoveredConversationId || !conversationDescription) return;
    const sync = async () => {
      try {
        const existing = await db.getConversation(discoveredConversationId);
        if (existing) {
          if (existing.description !== conversationDescription) {
            const updated: IConversation = {
              ...existing,
              title: conversationDescription,
              description: conversationDescription,
              updatedAt: new Date(),
            };
            await db.putConversation(updated);
          }
        } else {
          const created: IConversation = {
            id: discoveredConversationId,
            title: conversationDescription,
            description: conversationDescription,
            starred: false,
            isSystemGenerated: false,
            systemPurpose: null,
            isUnread: false,
            createdAt: new Date(),
            updatedAt: new Date(),
          };
          await db.putConversation(created);
          trackEvent(ANALYTICS_EVENTS.CHAT_CONVERSATION_CREATED, {
            conversationId: discoveredConversationId,
            source: "voice_agent",
          });
          trackEvent(ANALYTICS_EVENTS.FEATURE_DISCOVERED, {
            feature: "voice_agent",
          });
        }
        useChatStore
          .getState()
          .setActiveConversationId(discoveredConversationId);
      } catch (e) {
        console.error("[VoiceControlBar] failed to sync conversation", e);
      }
    };
    sync();
  }, [discoveredConversationId, conversationDescription]);

  // Single ready-check timer from session start. The ref keeps the check on
  // the CURRENT agent state — depending on `agentState` instead would restart
  // the countdown on every transition, so it would never measure "ready within
  // N seconds of joining".
  const agentStateRef = useRef(agentState);
  agentStateRef.current = agentState;
  useEffect(() => {
    const timer = setTimeout(() => {
      const state = agentStateRef.current;
      const isReady =
        state === "listening" || state === "thinking" || state === "speaking";
      if (!isReady) {
        const reason =
          state === "connecting"
            ? "Agent did not join the room."
            : "Agent connected but did not complete initializing.";
        toast.error(`Session ended: ${reason}`);
      }
    }, SESSION_READY_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, []);

  const sessionValue: VoiceSessionValue = useMemo(
    () => ({
      spectrum: voice.spectrum,
      agentState,
      conversationId,
      isConnecting,
      animationPaused,
      sendUserTurn,
    }),
    [
      voice.spectrum,
      agentState,
      conversationId,
      isConnecting,
      animationPaused,
      sendUserTurn,
    ],
  );

  return (
    <VoiceSessionProvider value={sessionValue}>
      <RoomAudioRenderer />
      {/* Only rendered while the browser's autoplay policy blocks playback —
          without a visible unlock control the agent speaks silently (the
          waveform still moves because it reads the raw track, not the
          audible output). */}
      <StartAudio
        label="Tap to enable sound"
        className="fixed top-16 left-1/2 z-50 -translate-x-1/2 cursor-pointer rounded-full bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground shadow-lg transition-transform hover:scale-105"
      />
      {children}
    </VoiceSessionProvider>
  );
}

/**
 * Voice session root. Owns the LiveKit `Room` and renders the session
 * provider. Has no UI of its own — children flow inside the provider so the
 * gradient (background) and the bar (bottom slot) can compose at the
 * `ChatPage` level.
 */
export function VoiceControlBarContainer({
  children,
}: VoiceControlBarContainerProps) {
  const { id: convoIdParam } = useParams<{ id: string }>();
  const room = useMemo(() => new Room(), []);
  const [sessionStarted, setSessionStarted] = useState(false);
  // Use the store's discoveredConversationId (seeded by enterVoiceMode) so the
  // token request always carries the right conversation ID from the very first
  // fetch — even for new conversations where convoIdParam is undefined.
  const storeConversationId = useDiscoveredConversationId();
  const voiceConversationId = storeConversationId ?? convoIdParam ?? undefined;
  const { existingOrRefreshConnectionDetails } =
    useConnectionDetails(voiceConversationId);

  const connectionDetailsRef = useRef(existingOrRefreshConnectionDetails);
  useEffect(() => {
    connectionDetailsRef.current = existingOrRefreshConnectionDetails;
  }, [existingOrRefreshConnectionDetails]);

  useEffect(() => {
    setSessionStarted(true);
  }, []);

  useEffect(() => {
    if (!sessionStarted) return;
    let aborted = false;
    if (room.state === "disconnected") {
      // Unlock audio playback NOW, while the voice-button click's user
      // activation is still valid. The agent's audio element is created
      // seconds later (post-connect, post-TTS) — far outside Chrome's
      // activation window — so without this the browser silently blocks
      // playback and the StartAudio fallback pill has to appear.
      room.startAudio().catch(() => {});
      Promise.all([
        room.localParticipant.setMicrophoneEnabled(true, undefined, {
          preConnectBuffer: true,
        }),
        connectionDetailsRef.current().then((connectionDetails) => {
          room.connect(
            connectionDetails.serverUrl,
            connectionDetails.participantToken,
          );
        }),
      ]).catch((error) => {
        if (aborted) return;
        toast.error(
          `There was an error connecting to the agent ${error.name}: ${error.message}`,
        );
      });
    }
    return () => {
      aborted = true;
      room.disconnect();
    };
  }, [room, sessionStarted]);

  return (
    <RoomContext.Provider value={room}>
      <VoiceSessionInner>{children}</VoiceSessionInner>
    </RoomContext.Provider>
  );
}

/**
 * The actual voice-mode bottom bar UI — connection-status chip + control
 * buttons. Must live inside `<VoiceControlBarContainer/>`. Use this as the
 * `bottomBar` prop to `ChatWithMessages` when voice mode is active.
 */
export function VoiceControlBarSlot({ onEndCall }: { onEndCall: () => void }) {
  // Pull session just to enforce the "must live inside container" contract
  // — the bar's pieces use the room/context themselves.
  const session = useVoiceSession();
  if (!session) return null;

  return (
    <div className="relative z-10 flex flex-col items-center">
      <VoiceConnectionStatus />
      <AgentControlBar onDisconnect={onEndCall} />
    </div>
  );
}
