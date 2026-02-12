import { useEffect, useRef } from "react";

import ProgressiveImage from "@/components/ui/ProgressiveImage";

export default function HeroImage({
  shouldHaveInitialFade = false,
  parallaxSpeed = 0.3,
}: {
  shouldHaveInitialFade?: boolean;
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
          webpSrc="/images/wallpapers/swiss.webp"
          pngSrc="/images/wallpapers/swiss.png"
          alt="wallpaper"
          className="object-cover"
          shouldHaveInitialFade={shouldHaveInitialFade}
        />
      </div>
    </div>
  );
}
