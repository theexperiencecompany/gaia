import { useVoiceAssistant } from "@livekit/components-react";
import { AnimatePresence, m } from "motion/react";

import {
  type AgentState,
  BarVisualizer,
} from "@/components/ui/elevenlabs-ui/bar-visualizer";
import { cn } from "@/lib/utils";

import { AgentTile } from "./agent-tile";
import { useAgentControlBar } from "./hooks/use-agent-control-bar";

const MotionAgentTile = m.create(AgentTile);

interface MediaTilesProps {
  chatOpen: boolean;
}

export function MediaTiles({ chatOpen }: MediaTilesProps) {
  const { state: agentState, audioTrack: agentAudioTrack } =
    useVoiceAssistant();

  // Get access to user's microphone
  const { micTrackRef } = useAgentControlBar();

  // Create MediaStream from the appropriate audio source
  const getMediaStream = () => {
    // When agent is speaking, show visualization for agent's audio
    if (agentState === "speaking" && agentAudioTrack?.publication?.track) {
      return new MediaStream([
        agentAudioTrack.publication.track.mediaStreamTrack,
      ]);
    }

    // When agent is listening or thinking, show visualization for user's microphone
    if (
      (agentState === "listening" || agentState === "thinking") &&
      micTrackRef.publication?.track
    ) {
      return new MediaStream([micTrackRef.publication.track.mediaStreamTrack]);
    }

    return undefined;
  };

  const mediaStream = getMediaStream();

  return (
    <div className="pointer-events-none mx-auto flex h-full w-full max-w-2xl items-center justify-center px-4 md:px-0">
      <AnimatePresence mode="popLayout">
        {!chatOpen ? (
          <MotionAgentTile
            key="orb"
            layout
            state={agentState}
            audioTrack={agentAudioTrack}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1.05 }}
            exit={{ opacity: 0, scale: 0.9 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className={cn(
              "flex h-[300px] w-[300px] items-center justify-center transition-all duration-300",
            )}
          />
        ) : (
          <m.div
            key="bar-visualizer"
            initial={{ opacity: 0, y: 10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.95 }}
            transition={{ duration: 0.4, ease: "easeInOut" }}
            className="flex h-full w-full max-w-xl justify-center"
          >
            <BarVisualizer
              state={agentState as AgentState}
              barCount={24}
              minHeight={5} // Much smaller minimum height for idle state
              maxHeight={120} // Keep high max for good range
              mediaStream={mediaStream}
              demo={!mediaStream}
              className="h-full w-full"
            />
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}
