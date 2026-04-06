"use client";

import { Button } from "@heroui/button";
import { CheckmarkCircle02Icon } from "@icons";
import { m } from "motion/react";
import Image from "next/image";
import type { FC } from "react";

const PLATFORMS = [
  {
    label: "Telegram",
    id: "telegram",
    icon: "/images/icons/macos/telegram.webp",
  },
  {
    label: "WhatsApp",
    id: "whatsapp",
    icon: "/images/icons/macos/whatsapp.webp",
  },
  {
    label: "Discord",
    id: "discord",
    icon: "/images/icons/macos/discord.webp",
  },
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
        className="flex items-center gap-2 ml-10.75"
      >
        <CheckmarkCircle02Icon className="size-4 text-emerald-500" />
        <span className="text-sm text-zinc-400">
          Connected. Your briefing will arrive on {connectedPlatform}.
        </span>
      </m.div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-2 ml-10.75">
      <div className="flex flex-wrap gap-2">
        {PLATFORMS.map((platform, index) => (
          <m.div
            key={platform.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: index * 0.08 }}
          >
            <Button
              variant="flat"
              className="pl-2 pr-3"
              startContent={
                <Image
                  src={platform.icon}
                  alt={platform.label}
                  width={26}
                  height={26}
                />
              }
              onPress={() => onConnect(platform.id)}
            >
              {platform.label}
            </Button>
          </m.div>
        ))}
      </div>
      <m.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.25, delay: PLATFORMS.length * 0.08 }}
      >
        <Button
          variant="light"
          size="sm"
          onPress={onSkip}
          className="text-zinc-500"
        >
          Skip for now
        </Button>
      </m.div>
    </div>
  );
};
