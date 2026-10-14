import type { ReactNode } from "react";
import { colors, fonts, OG_HEIGHT, OG_WIDTH } from "./lib";

const PAGE_BG = "#0b0b0c";
const WALLPAPER = "/images/wallpapers/bands_gradient_black.png";
const WALLPAPER_OPACITY = 0.55;

/** The raised card fill the referral images share, lit from the top. */
export const CARD_TOP = "#2c2c31";
export const CARD_BOTTOM = "#1f1f22";

interface WallpaperCardProps {
  baseUrl: string;
  /** The headline block between the wordmark and the footer. */
  children: ReactNode;
  footer: ReactNode;
  aside: ReactNode;
}

/** The referral OG frame: the GAIA wallpaper, the wordmark over a headline and footer, an aside on the right. */
export function WallpaperCard({
  baseUrl,
  children,
  footer,
  aside,
}: WallpaperCardProps) {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        position: "relative",
        backgroundColor: PAGE_BG,
        fontFamily: fonts.sans,
        color: colors.white,
      }}
    >
      {/* biome-ignore lint/performance/noImgElement: Satori renders plain img, next/image does not exist here. */}
      <img
        src={`${baseUrl}${WALLPAPER}`}
        alt=""
        width={OG_WIDTH}
        height={OG_HEIGHT}
        style={{
          position: "absolute",
          inset: 0,
          width: OG_WIDTH,
          height: OG_HEIGHT,
          objectFit: "cover",
          opacity: WALLPAPER_OPACITY,
        }}
      />
      <div
        style={{
          display: "flex",
          flex: 1,
          alignItems: "center",
          padding: "60px 72px",
          gap: 64,
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            flex: 1,
            height: "100%",
          }}
        >
          {/* biome-ignore lint/performance/noImgElement: Satori renders plain img, next/image does not exist here. */}
          <img
            src={`${baseUrl}/brand/gaia_wordmark_white.png`}
            alt="GAIA"
            height={32}
            style={{
              height: 32,
              objectFit: "contain",
              alignSelf: "flex-start",
            }}
          />
          {children}
          {footer}
        </div>
        {aside}
      </div>
    </div>
  );
}
