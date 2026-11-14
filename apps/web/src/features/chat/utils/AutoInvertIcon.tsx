"use client";

import { PackageOpenIcon } from "@icons";
import Image from "next/image";
import { useState } from "react";

/** An integration logo image that falls back to the package glyph when it fails to load. */
export const AutoInvertIcon: React.FC<{
  src: string;
  alt: string;
  size?: number;
  width?: number;
  height?: number;
  className?: string;
}> = ({ src, alt, size, width, height, className }) => {
  const [failed, setFailed] = useState(false);
  const displayWidth = width || size || 20;
  const displayHeight = height || size || 20;
  if (failed) {
    return (
      <PackageOpenIcon
        width={displayWidth}
        height={displayHeight}
        className={className ?? "text-zinc-400"}
      />
    );
  }
  // Border radius scales with the icon size (percentage radius) so small icons
  // aren't disproportionately rounded. object-contain keeps the logo intact.
  const imgClassName = `${className ?? ""} aspect-square rounded-[18%] object-contain`;
  // Eager: a lazy logo inside a clipped scroller (the slash menu's category
  // tabs) is not fetched until scrolled into view, so it showed up blank.
  const loading = "eager";

  // Use next/image in unoptimized mode for SVG URLs — SVGs can't pass through
  // the Next.js optimizer (they'd require dangerouslyAllowSVG), so they ship
  // straight from the source host.
  const isSvg = src.toLowerCase().endsWith(".svg");
  if (isSvg) {
    return (
      <Image
        alt={alt}
        width={displayWidth}
        height={displayHeight}
        className={imgClassName}
        loading={loading}
        src={src}
        unoptimized
        onError={() => setFailed(true)}
      />
    );
  }

  // Render the raster at a higher intrinsic resolution and constrain the
  // displayed box, so logos stay crisp on hi-dpi screens (Next optimizes down).
  return (
    <Image
      alt={alt}
      width={displayWidth * 3}
      height={displayHeight * 3}
      className={imgClassName}
      style={{ width: displayWidth, height: displayHeight }}
      loading={loading}
      src={src}
      onError={() => setFailed(true)}
    />
  );
};
