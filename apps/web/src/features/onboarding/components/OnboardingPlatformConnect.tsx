"use client";

import { CheckmarkCircle02Icon } from "@icons";
import { m } from "motion/react";
import type { FC } from "react";

const PLATFORMS = [
  { label: "Telegram", id: "telegram" },
  { label: "WhatsApp", id: "whatsapp" },
  { label: "Discord", id: "discord" },
] as const;

interface OnboardingPlatformConnectProps {
  onConnect: (platform: string) => void;
  onSkip: () => void;
  connectedPlatform: string | null;
}

export const OnboardingPlatformConnect: FC<OnboardingPlatformConnectProps> = ({
  onConnect,
  onSkip,
  connectedPlatform,
}) => {
  if (connectedPlatform) {
    return (
      <m.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="flex items-center gap-2"
      >
        <CheckmarkCircle02Icon className="size-4 text-emerald-500" />
        <span className="text-sm text-zinc-400">
          Connected. Your briefing will arrive on {connectedPlatform}.
        </span>
      </m.div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <div className="flex flex-wrap gap-2">
        {PLATFORMS.map((platform, index) => (
          <m.button
            key={platform.id}
            type="button"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: index * 0.08 }}
            className="cursor-pointer rounded-full border border-zinc-700/50 bg-zinc-800 px-4 py-2 text-sm text-zinc-300 transition-colors hover:bg-zinc-700"
            onClick={() => onConnect(platform.id)}
          >
            {platform.label}
          </m.button>
        ))}
      </div>
      <m.button
        type="button"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.25, delay: PLATFORMS.length * 0.08 }}
        className="cursor-pointer text-xs text-zinc-500 transition-colors hover:text-zinc-300"
        onClick={onSkip}
      >
        Skip
      </m.button>
    </div>
  );
};
