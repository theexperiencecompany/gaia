/**
 * Mini chat surface shown above the Telegram / WhatsApp / Slack / Discord
 * picker in the `platforms` onboarding stage. Auto-rotates through the
 * platforms on a timer; a `hoveredPlatform` prop (driven by the connect
 * buttons) overrides the rotation while the user hovers a button.
 *
 * Messages are profession-keyed via `getPlatformScript` — the archetype
 * mapping lives in `constants/platformPreviewMessages.ts`.
 *
 * Auto-scroll: as the cascade grows the message list, the inner scrollable
 * column (each platform variant uses `overflow-y-auto`) is pinned to its
 * bottom so the newest bubble stays visible inside the fixed-height frame.
 */

"use client";

import { Skeleton } from "@heroui/skeleton";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChatDemo } from "@/features/landing/components/iphone/ChatDemo";
import {
  cascadeDurationMs,
  useStaggeredMessages,
} from "@/features/landing/components/iphone/useStaggeredMessages";
import {
  getPlatformScript,
  PLATFORM_ICONS,
  PLATFORM_LABELS,
  PLATFORM_PREVIEW_ORDER,
  type PlatformPreviewPlatform,
} from "../constants/platformPreviewMessages";

const DWELL_MS = 1800;

interface OnboardingPlatformPreviewProps {
  profession: string | undefined;
  hoveredPlatform: PlatformPreviewPlatform | null;
  userName: string | undefined;
  userAvatar: string | undefined;
}

export function OnboardingPlatformPreview({
  profession,
  hoveredPlatform,
  userName,
  userAvatar,
}: OnboardingPlatformPreviewProps) {
  const [rotatingPlatform, setRotatingPlatform] =
    useState<PlatformPreviewPlatform>(PLATFORM_PREVIEW_ORDER[0]);

  const activePlatform = hoveredPlatform ?? rotatingPlatform;

  const script = useMemo(
    () =>
      getPlatformScript(profession, activePlatform, {
        name: userName,
        avatar: userAvatar,
      }),
    [profession, activePlatform, userName, userAvatar],
  );

  const [hasLoaded, setHasLoaded] = useState(false);
  useEffect(() => {
    const id = window.setTimeout(() => setHasLoaded(true), 350);
    return () => window.clearTimeout(id);
  }, []);

  const visibleMessages = useStaggeredMessages(script.messages, hasLoaded);

  const scrollHostRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const scroller =
      scrollHostRef.current?.querySelector<HTMLElement>(".overflow-y-auto");
    if (!scroller) return;
    scroller.scrollTop = scroller.scrollHeight;
  }, [visibleMessages, activePlatform]);

  useEffect(() => {
    if (hoveredPlatform) return;
    const cascadeMs = cascadeDurationMs(script.messages.length);
    const id = window.setTimeout(() => {
      setRotatingPlatform((current) => {
        const idx = PLATFORM_PREVIEW_ORDER.indexOf(current);
        return PLATFORM_PREVIEW_ORDER[
          (idx + 1) % PLATFORM_PREVIEW_ORDER.length
        ];
      });
    }, cascadeMs + DWELL_MS);
    return () => window.clearTimeout(id);
  }, [hoveredPlatform, script]);

  return (
    <div
      className="ml-10.75 flex flex-col rounded-3xl bg-zinc-900 p-2.5"
      style={{ width: 500, minWidth: 500, maxWidth: 500 }}
    >
      <div className="mb-1.5 flex h-6 shrink-0 items-center gap-2 px-1">
        <AnimatePresence mode="wait" initial={false}>
          <m.div
            key={activePlatform}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2 }}
            className="flex items-center gap-1.5"
          >
            <Image
              src={PLATFORM_ICONS[activePlatform]}
              alt=""
              width={18}
              height={18}
              className="rounded-[4px]"
              aria-hidden
            />
            <span className="text-[11px] text-zinc-500">
              Demo via {PLATFORM_LABELS[activePlatform]}
            </span>
          </m.div>
        </AnimatePresence>
      </div>
      <div
        ref={scrollHostRef}
        className="relative shrink-0 overflow-hidden rounded-2xl"
        style={{ height: 280, minHeight: 280, maxHeight: 280 }}
      >
        {hasLoaded ? (
          <AnimatePresence mode="wait" initial={false}>
            <m.div
              key={activePlatform}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="absolute inset-0"
            >
              <ChatDemo
                platform={activePlatform}
                messages={visibleMessages}
                title={script.title}
                subtitle={script.subtitle}
                showComposer={false}
                showHeader={false}
              />
            </m.div>
          </AnimatePresence>
        ) : (
          <Skeleton className="absolute inset-0 rounded-2xl" />
        )}
      </div>
    </div>
  );
}
