"use client";

import { Tooltip } from "@heroui/tooltip";
import * as m from "motion/react-m";
import NextImage from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  DiscordIcon,
  Github,
  TwitterIcon,
  WhatsappIcon,
} from "@/components/shared/icons";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import {
  getNextTimeOfDay,
  getTimeOfDay,
  isDarkTimeOfDay,
  type TimeOfDay,
} from "@/features/landing/utils/timeOfDay";

import GetStartedButton from "../shared/GetStartedButton";
import { TextSoftBlurIn } from "../shared/TextSoftBlurIn";
import { TimeOfDayToggle } from "../shared/TimeOfDayToggle";

const SWISS_KID_WALLPAPERS: Record<TimeOfDay, { webp: string; png: string }> = {
  morning: {
    webp: "/images/wallpapers/swiss kid morning.webp",
    png: "/images/wallpapers/swiss kid morning.png",
  },
  day: {
    webp: "/images/wallpapers/swiss kid day.webp",
    png: "/images/wallpapers/swiss kid day.png",
  },
  evening: {
    webp: "/images/wallpapers/swiss kid evening.webp",
    png: "/images/wallpapers/swiss kid evening.png",
  },
  night: {
    webp: "/images/wallpapers/swiss kid night.webp",
    png: "/images/wallpapers/swiss kid night.png",
  },
};

export const SOCIAL_LINKS = [
  {
    href: "https://twitter.com/trygaia",
    ariaLabel: "Twitter",
    buttonProps: {
      color: "#1a8cd8",
      className: "rounded-xl text-white!",
      "aria-label": "Twitter Link Button",
    },
    username: "@trygaia",
    icon: <TwitterIcon width={20} height={20} aria-hidden="true" />,
    label: "Twitter",
    description: "Follow us for updates",
    color: "#1a8cd8",
  },
  {
    href: "https://whatsapp.heygaia.io",
    ariaLabel: "WhatsApp",
    buttonProps: {
      color: "#1a9e4a",
      className: "rounded-xl text-white!",
      "aria-label": "WhatsApp Link Button",
    },
    icon: <WhatsappIcon width={20} height={20} aria-hidden="true" />,
    label: "WhatsApp",
    description: "Chat with our community",
    color: "#1a9e4a",
  },
  {
    href: "https://discord.heygaia.io",
    ariaLabel: "Discord",
    buttonProps: {
      color: "#5865f2",
      className: "rounded-xl text-white!",
      "aria-label": "Discord Link Button",
    },
    icon: <DiscordIcon width={20} height={20} aria-hidden="true" />,
    label: "Discord",
    description: "Join our community server",
    color: "#5865f2",
  },
  {
    href: "https://github.com/theexperiencecompany/gaia",
    ariaLabel: "GitHub",
    buttonProps: {
      color: "#1c1c1c",
      className: "rounded-xl text-white!",
      "aria-label": "GitHub Link Button",
    },
    icon: <Github width={20} height={20} aria-hidden="true" />,
    label: "GitHub",
    description: "Star and contribute",
    color: "#000000",
  },
];

export default function FinalSection({
  showSocials = true,
  timeOfDay: timeOfDayProp,
  isDark: isDarkProp,
  onTextClick,
  onTimeChange,
}: {
  showSocials?: boolean;
  timeOfDay?: TimeOfDay;
  isDark?: boolean;
  onTextClick?: () => void;
  onTimeChange?: () => void;
}) {
  const [internalTimeOfDay, setInternalTimeOfDay] = useState<TimeOfDay>(() =>
    getTimeOfDay(),
  );
  const [internalClickCount, setInternalClickCount] = useState(0);

  const timeOfDay = timeOfDayProp ?? internalTimeOfDay;
  const isDark =
    isDarkProp !== undefined ? isDarkProp : isDarkTimeOfDay(timeOfDay);

  const handleInternalClick = () => {
    const next = internalClickCount + 1;
    setInternalClickCount(next);
    if (next % 3 === 0) {
      setInternalTimeOfDay((prev) => getNextTimeOfDay(prev));
    }
  };

  const handleTimeChange =
    onTimeChange ??
    (() => {
      setInternalTimeOfDay((prev) => getNextTimeOfDay(prev));
    });

  const wallpaper = SWISS_KID_WALLPAPERS[timeOfDay];

  const [previousTime, setPreviousTime] = useState<TimeOfDay | null>(null);
  const lastTimeRef = useRef<TimeOfDay>(timeOfDay);

  if (timeOfDay !== lastTimeRef.current) {
    setPreviousTime(lastTimeRef.current);
    lastTimeRef.current = timeOfDay;
  }

  const [shouldPreloadOthers, setShouldPreloadOthers] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setShouldPreloadOthers(true), 1200);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="relative m-0! flex min-h-screen w-full flex-col items-center justify-center gap-4 overflow-hidden px-4 sm:px-6">
      {shouldPreloadOthers && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed left-0 top-0 h-px w-px overflow-hidden opacity-0"
        >
          {Object.entries(SWISS_KID_WALLPAPERS)
            .filter(([t]) => t !== timeOfDay)
            .map(([t, { webp }]) => (
              <NextImage
                key={t}
                src={webp}
                alt=""
                width={1920}
                height={1080}
                sizes="100vw"
                loading="eager"
              />
            ))}
        </div>
      )}

      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[20vh] bg-linear-to-t from-background to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-[30vh] bg-linear-to-b from-background to-transparent" />
      <div className="absolute bottom-6 right-6 z-[1002]">
        <TimeOfDayToggle timeOfDay={timeOfDay} onPress={handleTimeChange} />
      </div>

      {previousTime && (
        <div
          key={`prev-${previousTime}`}
          className="absolute bottom-0 left-0 right-0 z-0"
        >
          <ProgressiveImage
            webpSrc={SWISS_KID_WALLPAPERS[previousTime].webp}
            pngSrc={SWISS_KID_WALLPAPERS[previousTime].png}
            alt="Wallpaper"
            className="object-cover object-bottom"
            shouldHaveInitialFade={false}
            priority={false}
          />
        </div>
      )}

      <m.div
        key={timeOfDay}
        className="absolute bottom-0 left-0 right-0 z-0"
        initial={previousTime ? { clipPath: "circle(0% at 100% 50%)" } : false}
        animate={{ clipPath: "circle(150% at 100% 50%)" }}
        transition={{ duration: 0.5, ease: [0.65, 0, 0.35, 1] }}
        onAnimationComplete={() => setPreviousTime(null)}
      >
        <ProgressiveImage
          webpSrc={wallpaper.webp}
          pngSrc={wallpaper.png}
          alt="Wallpaper"
          className="object-cover object-bottom"
          shouldHaveInitialFade={true}
          priority={false}
        />
      </m.div>

      <div
        className={`relative z-20 ${showSocials ? "mb-30" : "mb-10"} flex h-full flex-col items-center justify-start gap-4`}
      >
        <div
          onClick={onTextClick ?? handleInternalClick}
          className="cursor-default select-none"
        >
          <TextSoftBlurIn
            text="Stop doing everything yourself."
            as="h2"
            className="z-10 text-center text-[2.2rem] font-serif font-normal sm:text-5xl md:text-8xl tracking-tight leading-snug text-white"
            gradient={
              isDark || timeOfDay === "morning"
                ? "linear-gradient(to bottom, #ffffff, #dbdbdb)"
                : "linear-gradient(to bottom, #837e88, #000000)"
            }
          />
        </div>

        <div
          className={`z-1 mb-6 max-w-(--breakpoint-md) px-4 py-0 text-center text-base leading-6 font-light tracking-tighter sm:px-0 sm:text-xl sm:leading-7 md:text-2xl ${isDark ? "text-white" : "text-white"}`}
        >
          Join thousands of professionals who gave their grunt work to GAIA.
        </div>
        <div className="flex gap-4">
          <GetStartedButton
            btnColor={isDark ? "#00bbff" : "#000000"}
            classname={
              isDark
                ? "text-black! text-lg h-12 px-2 rounded-2xl hover:scale-105"
                : "text-white! text-lg h-12 px-2 rounded-2xl hover:scale-105"
            }
            text="Try GAIA Free"
          />
          <GetStartedButton
            btnColor="#ffffff"
            classname="text-lg h-12 px-2 rounded-2xl hover:scale-105"
            text="Explore"
            href="/use-cases"
          />
        </div>
        <p
          className={`text-sm font-light mt-1 ${isDark ? "text-zinc-400" : "text-white/60"}`}
        >
          Free forever for personal use. No credit card.
        </p>

        {showSocials && (
          <div className="mt-4 flex items-center gap-3 sm:mt-6 sm:gap-2">
            {SOCIAL_LINKS.map(
              ({ href, ariaLabel, buttonProps, icon, label }, index) => {
                const color = `hover:text-[${buttonProps.color}]`;
                return (
                  <Tooltip
                    content={label}
                    placement="bottom"
                    key={index + href}
                  >
                    <Link
                      href={href}
                      aria-label={ariaLabel}
                      className={`flex w-10 scale-110 justify-center p-1 transition hover:scale-125 sm:w-10 sm:scale-125 sm:hover:scale-150 ${color}`}
                    >
                      {icon}
                    </Link>
                  </Tooltip>
                );
              },
            )}
          </div>
        )}
      </div>
    </div>
  );
}
