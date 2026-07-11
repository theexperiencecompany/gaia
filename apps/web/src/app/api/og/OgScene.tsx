import type { ReactNode } from "react";

import { colors, fonts, OG_HEIGHT, OG_WIDTH } from "./shared";

interface OgSceneProps {
  wallpaperUrl: string;
  /** Icon row rendered above the title (logos, favicons, …). */
  header?: ReactNode;
  title: string;
  subtitle: string;
}

/**
 * Shared bottom-anchored OG scene: wallpaper + dark gradient, optional icon
 * header, serif headline, subtitle, and the site footer. Used by the
 * per-slug OG routes (compare, persona) so they only differ in data.
 */
export function OgScene({
  wallpaperUrl,
  header,
  title,
  subtitle,
}: OgSceneProps) {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        position: "relative",
        fontFamily: fonts.sans,
      }}
    >
      {/* biome-ignore lint/performance/noImgElement: og image */}
      <img
        src={wallpaperUrl}
        alt="Background"
        width={OG_WIDTH}
        height={OG_HEIGHT}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: "center",
        }}
      />

      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background:
            "linear-gradient(180deg, rgba(9,9,11,0.6) 0%, rgba(9,9,11,0.8) 60%, rgba(9,9,11,0.95) 100%)",
        }}
      />

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          flex: 1,
          justifyContent: "flex-end",
          gap: 24,
          padding: "48px 64px",
          position: "relative",
          zIndex: 1,
        }}
      >
        {header}

        <div
          style={{
            display: "flex",
            fontSize: 92,
            fontWeight: 400,
            color: colors.white,
            fontFamily: fonts.serif,
            lineHeight: 1.1,
            textShadow: "0 4px 24px rgba(0,0,0,0.4)",
          }}
        >
          {title}
        </div>

        <div
          style={{
            display: "flex",
            fontSize: 30,
            color: colors.mutedLight,
            lineHeight: 1.45,
            fontWeight: 100,
            textShadow: "0 2px 8px rgba(0,0,0,0.4)",
          }}
        >
          {subtitle}
        </div>

        <div
          style={{
            display: "flex",
            fontSize: 24,
            color: colors.mutedLight,
            textShadow: "0 2px 8px rgba(0,0,0,0.4)",
          }}
        >
          heygaia.io
        </div>
      </div>
    </div>
  );
}

export function OgSceneLogo({ src, alt }: { src: string; alt: string }) {
  return (
    /* biome-ignore lint/performance/noImgElement: og image */
    <img
      src={src}
      alt={alt}
      width={88}
      height={88}
      style={{ borderRadius: 20, objectFit: "contain" }}
    />
  );
}
