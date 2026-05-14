"use client";

import { Button, ButtonGroup } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import {
  ArrowDown01Icon,
  CallEnd02Icon,
  Mic01Icon,
  MicOff01Icon,
} from "@icons";
import { useEffect, useMemo, useState } from "react";
import { useVoiceSpectrum } from "./useVoiceSpectrum";
import { VoiceGradient, type VoiceMode } from "./VoiceGradient";

export default function VoiceGradientDemoPage() {
  const [mode, setMode] = useState<VoiceMode>("gaia");
  // GAIA mode runs synthetic + mic (hybrid) so the demo still reacts to
  // your voice even when "GAIA speaking" is selected.
  const source = useMemo(() => {
    if (mode === "gaia") return "hybrid" as const;
    return "mic" as const;
  }, [mode]);

  const voice = useVoiceSpectrum({ source });

  // Start the mic immediately so hybrid mode has audio data even before the
  // user toggles into "You're speaking".
  useEffect(() => {
    if (!voice.isActive && !voice.error) {
      voice.start();
    }
  }, [voice.isActive, voice.error, voice.start]);

  return (
    <div className="relative h-[100dvh] w-full overflow-hidden bg-black">
      <VoiceGradient mode={mode} spectrum={voice.spectrum} />

      <div className="relative z-10 flex h-full flex-col">
        <div className="flex justify-center pt-10">
          <ButtonGroup variant="flat" radius="full" size="sm">
            <Button
              className={
                mode === "user"
                  ? "bg-white text-black"
                  : "bg-zinc-800/70 text-zinc-300"
              }
              onPress={() => setMode("user")}
            >
              You're speaking
            </Button>
            <Button
              className={
                mode === "gaia"
                  ? "bg-[#00bbff] text-black"
                  : "bg-zinc-800/70 text-zinc-300"
              }
              onPress={() => setMode("gaia")}
            >
              GAIA speaking
            </Button>
          </ButtonGroup>
        </div>

        <div className="flex-1" />

        <div className="flex flex-col items-center gap-3 pb-10">
          <div className="text-xs font-medium text-zinc-500">
            {voice.error
              ? `Mic error: ${voice.error}`
              : !voice.isActive
                ? "Requesting microphone..."
                : voice.isMuted
                  ? "Mic muted"
                  : mode === "gaia"
                    ? "GAIA speaking — synthesised voice with your mic blended in"
                    : "Speak — wave morphs with your voice spectrum"}
          </div>

          <div className="flex items-center gap-3">
            <ButtonGroup variant="flat" radius="full">
              <Button
                isIconOnly
                className="bg-zinc-800/80 text-white backdrop-blur"
                onPress={voice.toggleMute}
                aria-label={voice.isMuted ? "Unmute" : "Mute"}
              >
                {voice.isMuted ? (
                  <MicOff01Icon className="h-5 w-5" />
                ) : (
                  <Mic01Icon className="h-5 w-5" />
                )}
              </Button>
              <Dropdown placement="top">
                <DropdownTrigger>
                  <Button
                    isIconOnly
                    className="bg-zinc-800/80 text-white backdrop-blur"
                    aria-label="Select microphone"
                  >
                    <ArrowDown01Icon className="h-4 w-4" />
                  </Button>
                </DropdownTrigger>
                <DropdownMenu
                  aria-label="Audio input devices"
                  selectionMode="single"
                  selectedKeys={voice.deviceId ? [voice.deviceId] : []}
                  onAction={(key) => voice.selectDevice(String(key))}
                >
                  {voice.devices.length > 0 ? (
                    voice.devices.map((d) => (
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

            <Button
              isIconOnly
              radius="full"
              color="danger"
              onPress={voice.stop}
              aria-label="Disconnect"
            >
              <CallEnd02Icon className="h-5 w-5" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
