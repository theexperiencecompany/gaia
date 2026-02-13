"use client";

import {
  RoomAudioRenderer,
  RoomContext,
  StartAudio,
} from "@livekit/components-react";
import { Room } from "livekit-client";
import { m } from "motion/react";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import useConnectionDetails from "@/features/chat/components/voice-agent/hooks/useConnectionDetails";
import { SessionView } from "@/features/chat/components/voice-agent/session-view";

const MotionSessionView = m.create(SessionView);

interface AppProps {
  onEndCall: () => void;
}

export function VoiceApp({ onEndCall }: AppProps) {
  const room = useMemo(() => new Room(), []);
  const [sessionStarted, setSessionStarted] = useState(false);
  const pathname = usePathname();
  let conversationId: string | undefined;
  const match = pathname.match(/^\/c(?:\/([^/?#]+))?/);
  if (match?.[1]) {
    conversationId = match[1];
  }
  const { existingOrRefreshConnectionDetails } =
    useConnectionDetails(conversationId);

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
    <div className="flex h-full w-full flex-col">
      <RoomContext.Provider value={room}>
        <RoomAudioRenderer />
        <StartAudio label="Start Audio" />
        <MotionSessionView
          key="session-view"
          disabled={!sessionStarted}
          sessionStarted={sessionStarted}
          initial={{ opacity: 0 }}
          animate={{ opacity: sessionStarted ? 1 : 0 }}
          transition={{
            duration: 0.5,
            ease: "linear",
            delay: sessionStarted ? 0.5 : 0,
          }}
          onEndCall={onEndCall}
        />
      </RoomContext.Provider>
    </div>
  );
}
