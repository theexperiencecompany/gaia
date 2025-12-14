import NextImage from "next/image";
import { useState } from "react";

interface ProgressiveImageProps {
  webpSrc: string;
  pngSrc: string;
  alt: string;
  className?: string;
  shouldHaveInitialFade?: boolean;
  priority?: boolean;
  sizes?: string;
}

/**
 * Progressive image component that loads a WEBP version first for fast initial render,
 * then overlays a higher quality PNG version when it loads.
 */
export default function ProgressiveImage({
  webpSrc,
  pngSrc,
  alt,
  className = "object-cover",
  shouldHaveInitialFade = false,
  priority = true,
  sizes = "100vw",
}: ProgressiveImageProps) {
  const [initialLoaded, setInitialLoaded] = useState(false);
  const [loaded, setLoaded] = useState(false);

  return (
    <div className="relative h-full w-full">
      {/* Base WEBP visible immediately */}
      <NextImage
        src={webpSrc}
        alt={`${alt} webp`}
        fill
        priority={priority}
        sizes={sizes}
        onLoad={() => setInitialLoaded(true)}
        className={`${className} transition duration-200 ${initialLoaded || !shouldHaveInitialFade ? "opacity-100" : "opacity-0"}`}
      />

      {/* PNG fades in later */}
      <NextImage
        src={pngSrc}
        alt={`${alt} png`}
        fill
        sizes={sizes}
        onLoad={() => setLoaded(true)}
        className={`${className} transition-opacity ${loaded ? "opacity-100" : "opacity-0"}`}
      />
    </div>
  );
}
