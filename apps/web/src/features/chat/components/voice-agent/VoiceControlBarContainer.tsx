"use client";

import {
  RoomAudioRenderer,
  RoomContext,
  StartAudio,
  useRoomContext,
  useVoiceAssistant,
} from "@livekit/components-react";
import type { TextStreamReader } from "livekit-client";
import { Room } from "livekit-client";
import { useParams, useRouter } from "next/navigation";
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
import { useLoadingStore } from "@/stores/loadingStore";
import {
  useDiscoveredConversationId,
  useVoiceModeActions,
} from "@/stores/voiceModeStore";

const SESSION_READY_TIMEOUT_MS = 10_000;

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
  const router = useRouter();
  const { state: agentState, audioTrack: agentAudioTrack } =
    useVoiceAssistant();
  const room = useRoomContext();
  const setLoading = useLoadingStore((s) => s.setLoading);

  const storeDiscoveredId = useDiscoveredConversationId();
  const { setDiscoveredConversationId } = useVoiceModeActions();
  const [conversationDescription, setConversationDescription] = useState<
    string | null
  >(null);

  const discoveredConversationId = storeDiscoveredId ?? convoIdParam ?? null;
  const conversationId = discoveredConversationId;

  useVoiceMessages(conversationId);

  useRoomConversationStreams({
    onConversationId: setDiscoveredConversationId,
    onConversationDescription: setConversationDescription,
  });

  // Auto-redirect to /c/:id once a new conversation id is discovered and the
  // URL is still on /c (no id). `router.replace` keeps the back button going
  // home, not to the now-stale /c.
  useEffect(() => {
    if (!discoveredConversationId) return;
    if (discoveredConversationId === convoIdParam) return;
    if (convoIdParam) return;
    router.replace(`/c/${discoveredConversationId}`, { scroll: false });
  }, [discoveredConversationId, convoIdParam, router]);

  // Chat loadingStore fires ONLY for `thinking`. `connecting` is covered by
  // the dedicated <VoiceConnectionStatus/> chip in VoiceControlBarSlot; if
  // we pumped the chat store there too, the text-mode loading copy
  // ("Borrowing someone else's notes") would surface while the room is
  // still negotiating.
  const lastIsLoadingRef = useRef(false);
  useEffect(() => {
    const isThinking = agentState === "thinking";
    if (isThinking === lastIsLoadingRef.current) return;
    lastIsLoadingRef.current = isThinking;
    setLoading(isThinking);
  }, [agentState, setLoading]);
  useEffect(() => () => setLoading(false), [setLoading]);

  const remoteTrack = useMemo(
    () => agentAudioTrack?.publication?.track?.mediaStreamTrack ?? null,
    [agentAudioTrack],
  );
  const isConnecting =
    agentState === "connecting" || room?.state !== "connected";
  const spectrumSource = isConnecting
    ? "loading"
    : agentState === "speaking" && remoteTrack
      ? "agent-track"
      : agentState === "listening"
        ? "mic"
        : "idle";
  const voice = useVoiceSpectrum({ source: spectrumSource, remoteTrack });

  // When the connecting state ends, fade the procedural loading jitter to
  // zero over ~300ms before the spectrum source switches to mic/agent-track.
  // The hook keeps emitting the "loading" source until source prop changes
  // (next render after isConnecting flips), and uses the decayed amplitude
  // for that final frame burst so the wave settles smoothly.
  const wasConnectingRef = useRef(isConnecting);
  useEffect(() => {
    if (wasConnectingRef.current && !isConnecting) {
      voice.decayLoading();
    }
    wasConnectingRef.current = isConnecting;
  }, [isConnecting, voice.decayLoading]);

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

  useEffect(() => {
    const timer = setTimeout(() => {
      const isReady =
        agentState === "listening" ||
        agentState === "thinking" ||
        agentState === "speaking";
      if (!isReady) {
        const reason =
          agentState === "connecting"
            ? "Agent did not join the room."
            : "Agent connected but did not complete initializing.";
        toast.error(`Session ended: ${reason}`);
      }
    }, SESSION_READY_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [agentState]);

  const sessionValue: VoiceSessionValue = useMemo(
    () => ({
      spectrum: voice.spectrum,
      agentState,
      conversationId,
      isConnecting,
    }),
    [voice.spectrum, agentState, conversationId, isConnecting],
  );

  return (
    <VoiceSessionProvider value={sessionValue}>
      <RoomAudioRenderer />
      <StartAudio label="Start Audio" />
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
  const { existingOrRefreshConnectionDetails } =
    useConnectionDetails(convoIdParam);

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
