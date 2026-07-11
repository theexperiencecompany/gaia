import { ImageResponse } from "next/og";

import { OgScene, OgSceneLogo } from "../OgScene";
import {
  colors,
  createErrorResponse,
  createFallbackResponse,
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
    const loadedFonts = await loadFonts(title, `${title}${tagline}heygaia.io`);

    return new ImageResponse(
      <OgScene
        wallpaperUrl={`${siteBaseUrl}${wallpapers.pricing.png}`}
        title={title}
        subtitle={tagline}
        header={
          <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
            <OgSceneLogo
              src={`${siteBaseUrl}/images/logos/logo.webp`}
              alt="GAIA"
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
              <OgSceneLogo
                src={`https://www.google.com/s2/favicons?domain=${comparison.domain}&sz=128`}
                alt={comparison.name}
              />
            ) : null}
          </div>
        }
      />,
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
