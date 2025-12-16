import type {
  TrackReference,
  AgentState as VoiceAgentState,
} from "@livekit/components-react";

import {
  Orb,
  type AgentState as OrbAgentState,
} from "@/components/ui/elevenlabs-ui/orb";
import { cn } from "@/lib/utils";

import { useAudioVolume } from "./hooks/useAudioVolume";

interface AgentAudioTileProps {
  state: VoiceAgentState;
  audioTrack: TrackReference;
  className?: string;
}

const mapAgentState = (livekitState: VoiceAgentState): OrbAgentState => {
  switch (livekitState) {
    case "listening":
      return "listening";
    case "thinking":
      return "thinking";
    case "speaking":
      return "talking";
    default:
      return null;
  }
};

export const AgentTile = ({
  state,
  audioTrack,
  className,
  ref,
}: React.ComponentProps<"div"> & AgentAudioTileProps) => {
  const { getInputVolume, getOutputVolume } = useAudioVolume(audioTrack);
  const orbState = mapAgentState(state);

  return (
    <div
      ref={ref}
      className={cn("relative flex items-center justify-center", className)}
    >
      <div className="relative aspect-square w-full max-w-[300px]">
        <Orb
          agentState={orbState}
          getInputVolume={getInputVolume}
          getOutputVolume={getOutputVolume}
          volumeMode="manual"
        />
      </div>
    </div>
  );
};
