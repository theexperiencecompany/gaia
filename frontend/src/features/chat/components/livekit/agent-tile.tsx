import {
  type AgentState as LivekitAgentState,
  type TrackReference,
} from "@livekit/components-react";

import {
  Orb,
  type AgentState as OrbAgentState,
} from "@/components/ui/elevenlabs-ui/orb";
import { cn } from "@/lib/utils";

import { useAudioVolume } from "./hooks/useAudioVolume";

interface AgentAudioTileProps {
  state: LivekitAgentState;
  audioTrack: TrackReference;
  className?: string;
}

const mapAgentState = (livekitState: LivekitAgentState): OrbAgentState => {
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
          colors={["#CADCFC", "#A0B9D1"]}
          agentState={orbState}
          getInputVolume={getInputVolume}
          getOutputVolume={getOutputVolume}
          volumeMode="manual"
        />
      </div>
    </div>
  );
};
