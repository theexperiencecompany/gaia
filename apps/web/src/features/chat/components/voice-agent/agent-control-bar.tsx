"use client";

import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { ArrowUp01Icon, PhoneOffIcon } from "@icons";
import { useRoomContext } from "@livekit/components-react";
import { Track } from "livekit-client";
import * as React from "react";
import {
  type UseAgentControlBarProps,
  useAgentControlBar,
} from "@/features/chat/components/voice-agent/hooks/use-agent-control-bar";
import { TrackToggle } from "@/features/chat/components/voice-agent/track-toggle";
import { cn } from "@/lib/utils";

export interface AgentControlBarProps
  extends React.HTMLAttributes<HTMLDivElement>,
    UseAgentControlBarProps {
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
  onDisconnect,
  _onDeviceError,
  ...props
}: AgentControlBarProps) {
  const [isDisconnecting, setIsDisconnecting] = React.useState(false);
  const [devices, setDevices] = React.useState<MediaDeviceInfo[]>([]);
  const [activeDeviceId, setActiveDeviceId] = React.useState<string | null>(
    null,
  );
  const room = useRoomContext();

  const { visibleControls, microphoneToggle, handleDisconnect } =
    useAgentControlBar({
      controls,
      saveUserChoices,
    });

  const refreshDevices = React.useCallback(async () => {
    try {
      const list = await navigator.mediaDevices.enumerateDevices();
      setDevices(list.filter((d) => d.kind === "audioinput"));
    } catch {
      setDevices([]);
    }
  }, []);

  // Refresh device list whenever the OS reports a hot-plug change. Initial
  // population is lazy: triggered on first dropdown open.
  React.useEffect(() => {
    const md = navigator.mediaDevices;
    if (!md?.addEventListener) return;
    const handler = () => {
      refreshDevices();
    };
    md.addEventListener("devicechange", handler);
    return () => md.removeEventListener("devicechange", handler);
  }, [refreshDevices]);

  // Surface the currently-active mic so the dropdown shows a check next to it.
  React.useEffect(() => {
    const track = room?.localParticipant?.getTrackPublication(
      Track.Source.Microphone,
    )?.track?.mediaStreamTrack;
    const id = track?.getSettings()?.deviceId ?? null;
    setActiveDeviceId(id);
  }, [room?.localParticipant, microphoneToggle.enabled]);

  const onLeave = async () => {
    setIsDisconnecting(true);
    handleDisconnect();
    setIsDisconnecting(false);
    onDisconnect?.();
  };

  const handleDeviceSelect = async (deviceId: string) => {
    if (!room) return;
    try {
      await room.switchActiveDevice("audioinput", deviceId, true);
      setActiveDeviceId(deviceId);
    } catch (error) {
      console.error("Failed to switch microphone device", error);
    }
  };

  return (
    <div
      className={cn("flex flex-col items-center justify-center p-3", className)}
      {...props}
    >
      <div className="flex flex-row items-center justify-center gap-6">
        <div className="flex items-center gap-1">
          <TrackToggle
            source={Track.Source.Microphone}
            enabled={microphoneToggle.enabled}
            pending={microphoneToggle.pending}
            onClick={() => microphoneToggle.toggle()}
            className="flex h-16 w-16 items-center justify-center rounded-full bg-gray-700/20 shadow-md transition-colors hover:bg-gray-700/30 active:bg-gray-700/30"
          />
          <Dropdown
            placement="top"
            onOpenChange={(open) => open && refreshDevices()}
          >
            <DropdownTrigger>
              <Button
                isIconOnly
                size="sm"
                radius="full"
                aria-label="Select microphone"
                className="h-8 w-8 bg-gray-700/20 text-white shadow-md hover:bg-gray-700/30"
              >
                <ArrowUp01Icon className="h-4 w-4" />
              </Button>
            </DropdownTrigger>
            <DropdownMenu
              aria-label="Audio input devices"
              selectionMode="single"
              selectedKeys={activeDeviceId ? [activeDeviceId] : []}
              onAction={(key) => handleDeviceSelect(String(key))}
            >
              {devices.length > 0 ? (
                devices.map((d) => (
                  <DropdownItem key={d.deviceId}>
                    {d.label || "Unnamed device"}
                  </DropdownItem>
                ))
              ) : (
                <DropdownItem key="__none" isReadOnly>
                  No devices detected
                </DropdownItem>
              )}
            </DropdownMenu>
          </Dropdown>
        </div>

        {visibleControls.leave && (
          <div className="flex items-center justify-center">
            <Button
              onClick={onLeave}
              disabled={isDisconnecting}
              className="flex h-16 w-16 items-center justify-center rounded-full bg-red-500/10 shadow-md transition-colors hover:bg-red-500/15 active:bg-red-500/20"
            >
              <PhoneOffIcon className="h-6! w-6! text-red-400" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
