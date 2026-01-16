"use client";

import { Button } from "@heroui/button";
import { useRemoteParticipants } from "@livekit/components-react";
import { Track } from "livekit-client";
import * as React from "react";
import {
  type UseAgentControlBarProps,
  useAgentControlBar,
} from "@/features/chat/components/voice-agent/hooks/use-agent-control-bar";
import { TrackToggle } from "@/features/chat/components/voice-agent/track-toggle";
import { Message01Icon, PhoneOffIcon } from "@/icons";
import { cn } from "@/lib/utils";

export interface AgentControlBarProps
  extends React.HTMLAttributes<HTMLDivElement>,
    UseAgentControlBarProps {
  onChatOpenChange?: (open: boolean) => void;
  onDisconnect?: () => void;
  _onDeviceError?: (error: { source: Track.Source; error: Error }) => void;
}

/**
 * A control bar specifically designed for voice assistant interfaces
 */
export function AgentControlBar({
  controls,
  saveUserChoices = true,
  className,
  onChatOpenChange,
  onDisconnect,
  _onDeviceError,
  ...props
}: AgentControlBarProps) {
  const participants = useRemoteParticipants();
  const [chatOpen, setChatOpen] = React.useState(false);
  const isAgentAvailable = participants.some((p) => p.isAgent);
  const [isDisconnecting, setIsDisconnecting] = React.useState(false);

  const { visibleControls, microphoneToggle, handleDisconnect } =
    useAgentControlBar({
      controls,
      saveUserChoices,
    });

  const onLeave = async () => {
    setIsDisconnecting(true);
    handleDisconnect();
    setIsDisconnecting(false);
    onDisconnect?.();
  };

  React.useEffect(() => {
    onChatOpenChange?.(chatOpen);
  }, [chatOpen, onChatOpenChange]);

  return (
    <div
      className={cn("flex flex-col items-center justify-center p-3", className)}
      {...props}
    >
      <div className="flex flex-row items-center justify-center gap-6">
        <div className="flex items-center justify-center">
          <TrackToggle
            source={Track.Source.Microphone}
            enabled={microphoneToggle.enabled}
            pending={microphoneToggle.pending}
            onClick={() => microphoneToggle.toggle()}
            className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-700/20 shadow-md transition-colors hover:bg-surface-700/30 active:bg-surface-700/30"
          />
        </div>

        <div className="flex items-center justify-center">
          <Button
            aria-label="Toggle chat"
            onClick={() => setChatOpen((prev) => !prev)}
            disabled={!isAgentAvailable}
            className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-700/20 shadow-md transition-colors hover:bg-surface-700/30 active:bg-surface-700/30"
          >
            <Message01Icon className="!h-6 !w-6 text-white" />
          </Button>
        </div>

        {visibleControls.leave && (
          <div className="flex items-center justify-center">
            <Button
              onClick={onLeave}
              disabled={isDisconnecting}
              className="flex h-16 w-16 items-center justify-center rounded-full bg-red-500/10 shadow-md transition-colors hover:bg-red-500/15 active:bg-red-500/20"
            >
              <PhoneOffIcon className="!h-6 !w-6 text-red-400" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
