import { useEffect, useRef, useState } from "react";

import ProgressiveImage from "@/components/ui/ProgressiveImage";

export default function HeroImage({
  shouldHaveInitialFade = false,
  parallaxSpeed = 0.3, // 0.5 = moves at half speed (slower), 1 = normal speed, 0 = fixed
}: {
  shouldHaveInitialFade?: boolean;
  parallaxSpeed?: number;
}) {
  const [offsetY, setOffsetY] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleScroll = () => {
      if (!containerRef.current) return;

      setOffsetY(window.scrollY * parallaxSpeed);
    };

    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, [parallaxSpeed]);

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      <div
        style={{
          transform: `translateY(${-offsetY}px)`,
          willChange: "transform",
        }}
        className="absolute inset-0 h-full w-full"
      >
        <div className="pointer-events-none absolute inset-x-0 -top-20 z-10 h-[30vh] bg-linear-to-b from-background to-transparent opacity-50" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[20vh] bg-linear-to-t from-background to-transparent" />

        <ProgressiveImage
          webpSrc="/images/wallpapers/g3.webp"
          pngSrc="/images/wallpapers/g3.png"
          alt="wallpaper"
          className="object-cover"
          shouldHaveInitialFade={shouldHaveInitialFade}
        />
      </div>
    </div>
  );
}
