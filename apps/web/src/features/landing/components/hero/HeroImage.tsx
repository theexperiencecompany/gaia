import { useEffect, useRef } from "react";

import ProgressiveImage from "@/components/ui/ProgressiveImage";
import type { TimeOfDay } from "@/features/landing/utils/timeOfDay";

const WALLPAPERS: Record<TimeOfDay, { webp: string; png: string }> = {
  morning: {
    webp: "/images/wallpapers/swiss_morning.webp",
    png: "/images/wallpapers/swiss_morning.png",
  },
  day: {
    webp: "/images/wallpapers/swiss.webp",
    png: "/images/wallpapers/swiss.png",
  },
  evening: {
    webp: "/images/wallpapers/swiss_evening.webp",
    png: "/images/wallpapers/swiss_evening.png",
  },
  night: {
    webp: "/images/wallpapers/swiss_night.webp",
    png: "/images/wallpapers/swiss_night.png",
  },
};

export default function HeroImage({
  timeOfDay,
  parallaxSpeed = 0.3,
}: {
  timeOfDay: TimeOfDay;
  parallaxSpeed?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const transformRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const handleScroll = () => {
      if (rafRef.current !== null) return;
      rafRef.current = requestAnimationFrame(() => {
        if (transformRef.current)
          transformRef.current.style.transform = `translateY(${-(window.scrollY * parallaxSpeed)}px)`;
        rafRef.current = null;
      });
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", handleScroll);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [parallaxSpeed]);

  const wallpaper = WALLPAPERS[timeOfDay];

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      <div
        ref={transformRef}
        style={{
          willChange: "transform",
        }}
        className="absolute inset-0 h-full w-full"
      >
        <div className="pointer-events-none absolute inset-x-0 -top-20 z-10 h-[30vh] bg-linear-to-b from-background to-transparent opacity-50" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[20vh] bg-linear-to-t from-background to-transparent" />

        <ProgressiveImage
          webpSrc={wallpaper.webp}
          pngSrc={wallpaper.png}
          alt="wallpaper"
          className="object-cover"
          shouldHaveInitialFade={true}
        />
      </div>
    </div>
  );
}
