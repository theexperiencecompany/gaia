/**
 * Telegram / WhatsApp / Discord platform-link picker rendered by the
 * `platforms` stage. Once `connectedPlatform` is set, swaps to a
 * confirmation row instead of the buttons.
 *
 * Each button emits `onHoverPlatform` so the parent can drive a
 * preview surface above (`OnboardingPlatformPreview`).
 */

"use client";

import { Button } from "@heroui/button";
import { CheckmarkCircle02Icon } from "@icons";
import * as m from "motion/react-m";
import Image from "next/image";
import type { FC } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import type { PlatformPreviewPlatform } from "../constants/platformPreviewMessages";

const PLATFORMS = [
  {
    label: "Telegram",
    id: "telegram" as const,
    icon: "/images/icons/macos/telegram.webp",
  },
  {
    label: "WhatsApp",
    id: "whatsapp" as const,
    icon: "/images/icons/macos/whatsapp.webp",
  },
  {
    label: "Slack",
    id: "slack" as const,
    icon: "/images/icons/macos/slack.webp",
  },
  {
    label: "Discord",
    id: "discord" as const,
    icon: "/images/icons/macos/discord.webp",
  },
];

interface OnboardingPlatformConnectProps {
  onConnect: (platform: string) => void;
  onSkip: () => void;
  onHoverPlatform: (platform: PlatformPreviewPlatform | null) => void;
  connectedPlatform: string | null;
  hideSkip?: boolean;
}

export const OnboardingPlatformConnect: FC<OnboardingPlatformConnectProps> = ({
  onConnect,
  onSkip,
  onHoverPlatform,
  connectedPlatform,
  hideSkip = false,
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
      <div
        className="flex flex-wrap gap-2"
        onMouseLeave={() => onHoverPlatform(null)}
      >
        {PLATFORMS.map((platform, index) => (
          <m.div
            key={platform.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: index * 0.08 }}
            onMouseEnter={() => onHoverPlatform(platform.id)}
            onFocus={() => onHoverPlatform(platform.id)}
            onBlur={() => onHoverPlatform(null)}
          >
            <RaisedButton
              color="black"
              className="pl-2 pr-3"
              onClick={() => onConnect(platform.id)}
            >
              <Image
                src={platform.icon}
                alt={platform.label}
                width={100}
                height={100}
                className="size-6 max-h-6 max-w-6"
              />
              {platform.label}
            </RaisedButton>
          </m.div>
        ))}
      </div>
      {!hideSkip && (
        <m.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.25, delay: PLATFORMS.length * 0.08 }}
        >
          <Button
            variant="light"
            size="sm"
            onPress={onSkip}
            className="text-zinc-400 hover:text-zinc-200"
          >
            I'll do it later
          </Button>
        </m.div>
      )}
    </div>
  );
};
