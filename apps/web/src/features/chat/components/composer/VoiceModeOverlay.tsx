"use client";

import {
  RoomAudioRenderer,
  RoomContext,
  StartAudio,
} from "@livekit/components-react";
import { Room } from "livekit-client";
import { m } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import useConnectionDetails from "@/features/chat/components/voice-agent/hooks/useConnectionDetails";
import { SessionView } from "@/features/chat/components/voice-agent/session-view";
import { usePathname } from "@/i18n/navigation";
import { toast } from "@/lib/toast";

const MotionSessionView = m.create(SessionView);

interface AppProps {
  onEndCall: () => void;
}

export function VoiceApp({ onEndCall }: AppProps) {
  const room = useMemo(() => new Room(), []);
  const [sessionStarted, setSessionStarted] = useState(false);
  const [isConnecting, setIsConnecting] = useState(true);
  const onEndCallRef = useRef(onEndCall);
  const pathname = usePathname();
  let conversationId: string | undefined;
  const match = pathname.match(/^\/c(?:\/([^/?#]+))?/);
  if (match?.[1]) {
    conversationId = match[1];
  }
  const { existingOrRefreshConnectionDetails } =
    useConnectionDetails(conversationId);

  useEffect(() => {
    onEndCallRef.current = onEndCall;
  }, [onEndCall]);

  useEffect(() => {
    setSessionStarted(true);
  }, []);

  useEffect(() => {
    let aborted = false;
    if (sessionStarted && room.state === "disconnected") {
      Promise.all([
        room.localParticipant.setMicrophoneEnabled(true, undefined, {
          preConnectBuffer: true,
        }),
        existingOrRefreshConnectionDetails().then((connectionDetails) => {
          return room.connect(
            connectionDetails.serverUrl,
            connectionDetails.participantToken,
          );
        }),
      ])
        .then(() => {
          void room.startAudio().catch(() => {
            toast.info("Tap Start Audio to hear the voice response.");
          });
          if (!aborted) setIsConnecting(false);
        })
        .catch((error) => {
          if (aborted) return;
          toast.error(
            `There was an error connecting to the agent ${error.name}: ${error.message}`,
          );
          onEndCallRef.current();
        });
    }
    return () => {
      aborted = true;
      room.disconnect();
    };
  }, [room, sessionStarted]);

  return (
    <div className="flex h-full w-full flex-col">
      <RoomContext.Provider value={room}>
        <RoomAudioRenderer />
        <StartAudio label="Start Audio" />
        {isConnecting && (
          <div className="flex h-full w-full items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-zinc-400">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-600 border-t-zinc-300" />
              <span className="text-sm">Connecting to voice agent…</span>
            </div>
          </div>
        )}
        <MotionSessionView
          key="session-view"
          disabled={!sessionStarted || isConnecting}
          sessionStarted={sessionStarted}
          initial={{ opacity: 0 }}
          animate={{ opacity: sessionStarted && !isConnecting ? 1 : 0 }}
          transition={{
            duration: 0.5,
            ease: "linear",
            delay: sessionStarted && !isConnecting ? 0.5 : 0,
          }}
          onEndCall={onEndCall}
        />
      </RoomContext.Provider>
    </div>
  );
}
