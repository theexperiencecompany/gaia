"use client";

import { Spinner } from "@heroui/react";
import {
  EndCallButton,
  VoiceControlPill,
} from "@/features/chat/components/voice-agent/VoiceCallControls";

/** The voice bar while LiveKit's chunk loads: no room yet, but the call can already be ended. */
export function VoiceControlBarPending({
  onEndCall,
}: Readonly<{ onEndCall: () => void }>) {
  return (
    <div className="relative z-10 flex w-full flex-col items-center p-3">
      <VoiceControlPill>
        <div
          role="status"
          aria-label="Preparing voice mode"
          className="flex h-12 w-14 items-center justify-center"
        >
          <Spinner size="sm" color="current" className="text-zinc-300" />
        </div>
        <EndCallButton onPress={onEndCall} />
      </VoiceControlPill>
    </div>
  );
}
