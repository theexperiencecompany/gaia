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
  width?: number;
  height?: number;
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
  width = 1920,
  height = 1080,
}: ProgressiveImageProps) {
  const [initialLoaded, setInitialLoaded] = useState(false);
  const [loaded, setLoaded] = useState(false);

  return (
    <div className="relative h-full w-full">
      {/* Base WEBP visible immediately */}
      <NextImage
        src={webpSrc}
        alt={`${alt} webp`}
        width={width}
        height={height}
        priority={priority}
        sizes={sizes}
        onLoad={() => setInitialLoaded(true)}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
        className={`${className} transition duration-200 ${initialLoaded || !shouldHaveInitialFade ? "opacity-100" : "opacity-0"}`}
      />

      {/* PNG fades in later */}
      <NextImage
        src={pngSrc}
        alt={`${alt} png`}
        width={width}
        height={height}
        sizes={sizes}
        loading={priority ? "eager" : "lazy"}
        onLoad={() => setLoaded(true)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          position: "absolute",
          top: 0,
          left: 0,
        }}
        className={`${className} transition-opacity ${loaded ? "opacity-100" : "opacity-0"}`}
      />
    </div>
  );
}
