import NextImage from "next/image";
import { useState } from "react";

export default function HeroImage({
  shouldHaveInitialFade = false,
}: {
  shouldHaveInitialFade?: boolean;
}) {
  const [loaded, setLoaded] = useState(false);
  const [initialloaded, setInitialLoaded] = useState(false);

  return (
    <div className="relative h-full w-full">
      {/* Base WEBP visible immediately */}
      <NextImage
        src="/images/wallpapers/g3.webp"
        alt="wallpaper webp"
        fill
        priority
        sizes="100vw"
        onLoad={() => setInitialLoaded(true)}
        className={`object-cover duration-200 ${initialloaded || !shouldHaveInitialFade ? "opacity-100" : "opacity-0"} transition`}
      />

      {/* PNG fades in later */}
      <NextImage
        src="/images/wallpapers/g3.png"
        alt="wallpaper png"
        fill
        sizes="100vw"
        onLoad={() => setLoaded(true)}
        className={`object-cover transition-opacity ${loaded ? "opacity-100" : "opacity-0"}`}
      />
    </div>
  );
}
