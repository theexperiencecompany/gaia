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

  // Preload the alternate time-of-day wallpapers only once this bottom-of-page
  // section is near the viewport, so they don't compete with the hero's LCP
  // image (and the rest of the critical path) during initial page load.
  const containerRef = useRef<HTMLDivElement>(null);
  const [shouldPreloadOthers, setShouldPreloadOthers] = useState(false);
  useEffect(() => {
    const node = containerRef.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setShouldPreloadOthers(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setShouldPreloadOthers(true);
          observer.disconnect();
        }
      },
      { rootMargin: "400px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={containerRef}
      className="relative m-0! flex min-h-svh w-full flex-col items-center justify-center gap-4 overflow-hidden px-4 py-6 sm:px-6 sm:py-8"
    >
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

      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[40vh] sm:h-[25vh] bg-linear-to-t from-background via-background/80 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-[30vh] bg-linear-to-b from-background to-transparent" />
      <div className="absolute bottom-6 right-6 z-1002">
        <TimeOfDayToggle timeOfDay={timeOfDay} onPress={handleTimeChange} />
      </div>

      {previousTime && (
        <div key={`prev-${previousTime}`} className="absolute inset-0 z-0">
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
        className="absolute inset-0 z-0"
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
        className={`relative z-20 ${showSocials ? "mb-14 sm:mb-20 md:mb-30 max-[760px]:mb-6 max-[680px]:mb-2" : "mb-8 sm:mb-10 max-[760px]:mb-4"} flex h-full w-full max-w-5xl flex-col items-center justify-start gap-4 max-[760px]:gap-3 max-[680px]:gap-2`}
      >
        <div
          onClick={onTextClick ?? handleInternalClick}
          className="cursor-default select-none"
        >
          <TextSoftBlurIn
            text="Stop doing everything yourself."
            as="h2"
            className="z-10 px-2 text-center text-[clamp(2.8rem,8.3vw,5rem)] leading-[1.05] font-serif font-normal tracking-tight text-white md:text-6xl"
            gradient={
              isDark || timeOfDay === "morning"
                ? "linear-gradient(to bottom, #ffffff, #dbdbdb)"
                : "linear-gradient(to bottom, #837e88, #000000)"
            }
          />
        </div>

        <div className="z-1 mb-3 max-w-sm px-4 py-0 text-center text-base leading-6 font-light tracking-tighter text-white sm:mb-6 sm:max-w-(--breakpoint-md) sm:px-0 sm:text-xl sm:leading-7 md:text-2xl max-[760px]:mb-2 max-[760px]:text-[1.05rem] max-[760px]:leading-6">
          Join thousands of professionals who gave their grunt work to GAIA.
        </div>
        <div className="flex w-full max-w-sm flex-col gap-3 px-2 sm:w-auto sm:max-w-none sm:flex-row sm:gap-4 sm:px-0">
          <GetStartedButton
            btnColor={isDark ? "#00bbff" : "#000000"}
            classname={
              isDark
                ? "w-full sm:w-auto text-black! text-sm sm:text-lg h-9 sm:h-12 px-4 rounded-xl hover:scale-105"
                : "w-full sm:w-auto text-white! text-sm sm:text-lg h-9 sm:h-12 px-4 rounded-xl hover:scale-105"
            }
            text="Try GAIA Free"
          />
          <GetStartedButton
            btnColor="#ffffff"
            classname="w-full sm:w-auto text-sm sm:text-lg h-9 sm:h-12 px-4 rounded-xl hover:scale-105"
            text="Explore"
            href="/use-cases"
          />
        </div>
        <p
          className={`mt-1 text-sm font-light max-[760px]:text-xs ${isDark ? "text-zinc-400" : "text-white/60"}`}
        >
          Free forever for personal use. No credit card.
        </p>

        {showSocials && (
          <div className="mt-3 flex flex-wrap items-center justify-center gap-3 sm:mt-6 sm:gap-2 max-[700px]:hidden">
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
