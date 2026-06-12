"use client";

import {
  Button,
  ButtonGroup,
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/react";
import {
  ArrowDown01Icon,
  CallEnd04Icon,
  Mic02Icon,
  MicOff02Icon,
} from "@icons";
import { useRoomContext } from "@livekit/components-react";
import { Track } from "livekit-client";
import * as React from "react";
import {
  type UseAgentControlBarProps,
  useAgentControlBar,
} from "@/features/chat/components/voice-agent/hooks/use-agent-control-bar";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";

export interface AgentControlBarProps
  extends React.HTMLAttributes<HTMLDivElement>,
    UseAgentControlBarProps {
  onDisconnect?: () => void;
}

/**
 * A control bar specifically designed for voice assistant interfaces
 */
export function AgentControlBar({
  controls,
  saveUserChoices = true,
  className,
  onDisconnect,
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
      // Chrome only prompts for the mic ONCE per site; after a denial it
      // rejects silently, so surface a clear path back to the prompt.
      onDeviceError: ({ error }) => {
        if (error.name === "NotAllowedError") {
          toast.error(
            "Microphone access is blocked. Click the mic icon in the address bar to allow it, then unmute again.",
          );
        } else {
          toast.error(`Microphone error: ${error.message}`);
        }
      },
    });

  const micEnabled = microphoneToggle.enabled;
  const MicStateIcon = micEnabled ? Mic02Icon : MicOff02Icon;

  const handleMicPress = React.useCallback(() => {
    // Every mic-toggle click is a user gesture — reuse it to (re)unlock
    // audio playback too, so sound and mic both recover from one tap.
    room?.startAudio().catch(() => {});
    microphoneToggle.toggle();
  }, [room, microphoneToggle.toggle]);

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
      {/* One floating pill holds every control — iOS-call style. */}
      <div className="flex items-center gap-1.5 rounded-full bg-zinc-900/80 p-1.5 shadow-lg backdrop-blur-md">
        <ButtonGroup variant="flat" radius="full">
          <Button
            isIconOnly
            aria-label={micEnabled ? "Mute microphone" : "Unmute microphone"}
            isLoading={microphoneToggle.pending}
            onPress={handleMicPress}
            className="h-12 w-14 bg-zinc-800 text-white transition-colors hover:bg-zinc-700 active:bg-zinc-700"
          >
            <MicStateIcon className="h-6 w-6" />
          </Button>
          <Dropdown
            placement="top-end"
            onOpenChange={(open) => open && refreshDevices()}
          >
            <DropdownTrigger>
              <Button
                isIconOnly
                aria-label="Select microphone"
                className="h-12 w-9 bg-zinc-800 text-zinc-400 transition-colors hover:bg-zinc-700"
              >
                <ArrowDown01Icon className="h-4 w-4" />
              </Button>
            </DropdownTrigger>
            <DropdownMenu
              aria-label="Audio input devices"
              className="max-w-[300px]"
              selectionMode="single"
              disallowEmptySelection
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
        </ButtonGroup>

        {visibleControls.leave && (
          <Button
            isIconOnly
            radius="full"
            aria-label="End voice session"
            onPress={onLeave}
            isDisabled={isDisconnecting}
            className="h-12 w-14 bg-red-500/15 transition-colors hover:bg-red-500/20 active:bg-red-500/25"
          >
            <CallEnd04Icon className="h-6 w-6 text-red-400" />
          </Button>
        )}
      </div>
    </div>
  );
}
