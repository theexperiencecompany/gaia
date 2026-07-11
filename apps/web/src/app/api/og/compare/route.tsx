import { ImageResponse } from "next/og";
import {
  colors,
  createErrorResponse,
  createFallbackResponse,
  fonts,
  getBaseUrl,
  loadFonts,
  OG_HEIGHT,
  OG_WIDTH,
  truncateText,
  wallpapers,
} from "../shared";

export const runtime = "edge";

interface OgComparison {
  name?: string;
  tagline?: string;
  domain?: string;
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const slug = searchParams.get("slug");

    if (!slug) {
      return createFallbackResponse("GAIA Comparisons");
    }

    const siteBaseUrl = getBaseUrl(request.url);
    const wallpaperUrl = `${siteBaseUrl}${wallpapers.pricing.png}`;

    let comparison: OgComparison | null = null;
    try {
      // Comparison entries are public static assets — fetch straight from the site.
      const response = await fetch(
        `${siteBaseUrl}/data/comparisons/${slug}.json`,
        { cache: "no-store" },
      );
      if (response.ok) {
        comparison = await response.json();
      }
    } catch (e) {
      console.error("[OG Compare] Fetch failed:", e);
    }

    if (!comparison?.name) {
      return createFallbackResponse("GAIA Comparisons");
    }

    const title = `GAIA vs ${comparison.name}`;
    const tagline = truncateText(
      comparison.tagline ?? "An honest, side-by-side comparison.",
      140,
    );
    const allText = `${title}${tagline}Honest comparisonheygaia.io`;

    const loadedFonts = await loadFonts(title, allText);

    return new ImageResponse(
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
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 24,
            }}
          >
            {/* biome-ignore lint/performance/noImgElement: og image */}
            <img
              src={`${siteBaseUrl}/images/logos/logo.webp`}
              alt="GAIA"
              width={88}
              height={88}
              style={{ borderRadius: 20, objectFit: "contain" }}
            />
            <div
              style={{
                display: "flex",
                fontSize: 48,
                color: colors.mutedLight,
                fontWeight: 300,
              }}
            >
              vs
            </div>
            {comparison.domain ? (
              /* biome-ignore lint/performance/noImgElement: og image */
              <img
                src={`https://www.google.com/s2/favicons?domain=${comparison.domain}&sz=128`}
                alt={comparison.name}
                width={88}
                height={88}
                style={{ borderRadius: 20, objectFit: "contain" }}
              />
            ) : null}
          </div>

          <div
            style={{
              display: "flex",
              fontSize: 96,
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
            {tagline}
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
      </div>,
      {
        width: OG_WIDTH,
        height: OG_HEIGHT,
        fonts: loadedFonts.length > 0 ? loadedFonts : undefined,
      },
    );
  } catch (e: unknown) {
    console.error("OG Compare image generation failed:", e);
    return createErrorResponse();
  }
}
