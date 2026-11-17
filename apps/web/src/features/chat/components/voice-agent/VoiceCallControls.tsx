"use client";

import { CallEnd04Icon } from "@icons";
import type { ReactNode } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";

/** The floating iOS-call style pill that holds every voice control. */
export function VoiceControlPill({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 rounded-full bg-zinc-900/80 p-1.5 shadow-lg backdrop-blur-md">
      {children}
    </div>
  );
}

export function EndCallButton({
  onPress,
  isDisabled,
}: {
  onPress: () => void;
  isDisabled?: boolean;
}) {
  return (
    <GaiaButton
      shape="pill"
      isIconOnly
      aria-label="End voice session"
      onPress={onPress}
      isDisabled={isDisabled}
      variant="danger-soft"
      className="h-12 w-14 bg-red-500/15 transition-colors hover:bg-red-500/20 active:bg-red-500/25"
    >
      <CallEnd04Icon className="h-6 w-6 text-red-400" />
    </GaiaButton>
  );
}
