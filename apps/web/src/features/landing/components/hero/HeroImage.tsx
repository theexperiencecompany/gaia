import * as m from "motion/react-m";
import NextImage from "next/image";
import { useEffect, useRef, useState } from "react";
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

  const [previousTime, setPreviousTime] = useState<TimeOfDay | null>(null);
  const [lastTime, setLastTime] = useState<TimeOfDay>(timeOfDay);

  // Adjust state when the prop changes (the documented "adjusting state on prop
  // change" pattern) so the crossfade can render the outgoing wallpaper while
  // the new one animates in. Calling setState during render re-runs immediately
  // before commit; a ref mutation here is unsafe (React can discard the render).
  if (timeOfDay !== lastTime) {
    setPreviousTime(lastTime);
    setLastTime(timeOfDay);
  }

  const [shouldPreloadOthers, setShouldPreloadOthers] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setShouldPreloadOthers(true), 1200);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    let idleTimer: ReturnType<typeof setTimeout> | null = null;
    const handleScroll = () => {
      if (rafRef.current !== null) return;
      rafRef.current = requestAnimationFrame(() => {
        const el = transformRef.current;
        if (!el) return;
        // Promote the layer only while the parallax is actively moving; a
        // permanent will-change pins GPU memory for the page's lifetime.
        el.style.willChange = "transform";
        el.style.transform = `translateY(${-(window.scrollY * parallaxSpeed)}px)`;
        if (idleTimer !== null) clearTimeout(idleTimer);
        idleTimer = setTimeout(() => {
          if (transformRef.current) {
            transformRef.current.style.willChange = "auto";
          }
        }, 150);
        rafRef.current = null;
      });
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", handleScroll);
      if (idleTimer !== null) clearTimeout(idleTimer);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [parallaxSpeed]);

  const wallpaper = WALLPAPERS[timeOfDay];

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      {shouldPreloadOthers && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed left-0 top-0 h-px w-px overflow-hidden opacity-0"
        >
          {Object.entries(WALLPAPERS).flatMap(([t, { webp }]) =>
            t === timeOfDay
              ? []
              : [
                  <NextImage
                    key={t}
                    src={webp}
                    alt=""
                    width={1920}
                    height={1080}
                    sizes="100vw"
                    loading="eager"
                  />,
                ],
          )}
        </div>
      )}

      <div ref={transformRef} className="absolute inset-0 h-full w-full">
        <div className="pointer-events-none absolute inset-x-0 -top-20 z-10 h-[30vh] bg-linear-to-b from-background to-transparent opacity-50" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[20vh] bg-linear-to-t from-background to-transparent" />

        {previousTime && (
          <div
            key={`prev-${previousTime}`}
            className="absolute inset-0 h-full w-full"
          >
            <ProgressiveImage
              webpSrc={WALLPAPERS[previousTime].webp}
              pngSrc={WALLPAPERS[previousTime].png}
              alt="Hero wallpaper"
              className="object-cover"
              shouldHaveInitialFade={false}
              priority={false}
            />
          </div>
        )}

        <m.div
          key={timeOfDay}
          className="absolute inset-0 h-full w-full"
          initial={
            previousTime ? { clipPath: "circle(0% at 100% 50%)" } : false
          }
          animate={{ clipPath: "circle(150% at 100% 50%)" }}
          transition={{ duration: 0.5, ease: [0.65, 0, 0.35, 1] }}
          onAnimationComplete={() => setPreviousTime(null)}
        >
          <ProgressiveImage
            webpSrc={wallpaper.webp}
            pngSrc={wallpaper.png}
            alt="Hero wallpaper"
            className="object-cover"
            // LCP element: render immediately (no JS-gated opacity fade) so it
            // paints from the SSR HTML + preload as soon as bytes arrive, rather
            // than waiting for hydration + onLoad. Time-of-day transitions still
            // animate via the clip-path on the wrapping m.div.
            shouldHaveInitialFade={false}
            priority={true}
          />
        </m.div>
      </div>
    </div>
  );
}
