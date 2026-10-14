/**
 * Telegram / WhatsApp / iMessage platform-link picker for the `platformPick`
 * stage. Slack and Discord are deliberately absent — they live in
 * Settings → Linked accounts, which offers all five.
 *
 * The button's behaviour comes entirely from `onConnect`; this component
 * knows nothing about deep links or phone registration. Phase 7 upgrades
 * those links to carry a one-time code by changing `useConnectPlatform`
 * alone.
 *
 * Each button emits `onHoverPlatform` so the parent can drive the preview
 * surface above (`OnboardingPlatformPreview`); iMessage has no preview
 * script, so it reports `null`.
 */

"use client";

import { Button } from "@heroui/button";
import * as m from "motion/react-m";
import Image from "next/image";
import type { FC } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import {
  BOT_PLATFORM_ICONS,
  BOT_PLATFORM_LABELS,
  type BotPlatform,
} from "@/config/botPlatforms";
import type { PlatformPreviewPlatform } from "../constants/platformPreviewMessages";
import { isPreviewPlatform } from "../constants/platformPreviewMessages";

const PLATFORMS: BotPlatform[] = ["telegram", "whatsapp", "imessage"];

interface OnboardingPlatformConnectProps {
  onConnect: (platform: BotPlatform) => void;
  onSkip: () => void;
  onHoverPlatform: (platform: PlatformPreviewPlatform | null) => void;
  hideSkip?: boolean;
  embedded?: boolean;
}

const PlatformMention: FC<{ platform: BotPlatform }> = ({ platform }) => (
  <span className="inline-flex items-center gap-1 text-zinc-300">
    <Image
      src={BOT_PLATFORM_ICONS[platform]}
      alt=""
      width={100}
      height={100}
      className="size-3.5"
    />
    {BOT_PLATFORM_LABELS[platform]}
  </span>
);

export const OnboardingPlatformConnect: FC<OnboardingPlatformConnectProps> = ({
  onConnect,
  onSkip,
  onHoverPlatform,
  hideSkip = false,
  embedded = false,
}) => {
  const hover = (platform: BotPlatform) =>
    onHoverPlatform(isPreviewPlatform(platform) ? platform : null);

  return (
    <div
      className={
        embedded
          ? "flex flex-col items-start gap-2"
          : "flex flex-col items-start gap-2 sm:ml-10.75"
      }
    >
      <div
        className="flex flex-wrap gap-2"
        onMouseLeave={() => onHoverPlatform(null)}
      >
        {PLATFORMS.map((platform, index) => (
          <m.div
            key={platform}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: index * 0.08 }}
            onMouseEnter={() => hover(platform)}
            onFocus={() => hover(platform)}
            onBlur={() => onHoverPlatform(null)}
          >
            <RaisedButton
              color="black"
              className="pr-3 pl-2"
              onClick={() => onConnect(platform)}
            >
              <Image
                src={BOT_PLATFORM_ICONS[platform]}
                alt={BOT_PLATFORM_LABELS[platform]}
                width={100}
                height={100}
                className="size-6 max-h-6 max-w-6"
              />
              {BOT_PLATFORM_LABELS[platform]}
            </RaisedButton>
          </m.div>
        ))}
      </div>
      {!hideSkip && (
        <m.div
          className="flex flex-col items-start gap-1"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.25, delay: PLATFORMS.length * 0.08 }}
        >
          <Button variant="flat" size="md" onPress={onSkip}>
            Skip
          </Button>
          <p className="flex flex-wrap items-center gap-1 px-1 text-xs text-zinc-400">
            Don't worry, you can connect more platforms like
            <PlatformMention platform="slack" />
            and
            <PlatformMention platform="discord" />
            later.
          </p>
        </m.div>
      )}
    </div>
  );
};
