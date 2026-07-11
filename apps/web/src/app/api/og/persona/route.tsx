import { ImageResponse } from "next/og";

import { OgScene, OgSceneLogo } from "../OgScene";
import {
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

interface OgPersona {
  title?: string;
  role?: string;
  metaDescription?: string;
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const slug = searchParams.get("slug");

    if (!slug) {
      return createFallbackResponse("GAIA for Your Role");
    }

    const siteBaseUrl = getBaseUrl(request.url);

    let persona: OgPersona | null = null;
    try {
      // Persona entries are public static assets — fetch straight from the site.
      const response = await fetch(
        `${siteBaseUrl}/data/personas/${slug}.json`,
        { cache: "no-store" },
      );
      if (response.ok) {
        persona = await response.json();
      }
    } catch (e) {
      console.error("[OG Persona] Fetch failed:", e);
    }

    if (!persona?.role) {
      return createFallbackResponse("GAIA for Your Role");
    }

    const title = `GAIA for ${persona.role}`;
    const description = truncateText(
      persona.metaDescription ??
        "Workflows tuned for your job, not generic ones.",
      160,
    );
    const loadedFonts = await loadFonts(
      title,
      `${title}${description}heygaia.io`,
    );

    return new ImageResponse(
      <OgScene
        wallpaperUrl={`${siteBaseUrl}${wallpapers.useCases.png}`}
        title={title}
        subtitle={description}
        header={
          <OgSceneLogo
            src={`${siteBaseUrl}/images/logos/logo.webp`}
            alt="GAIA"
          />
        }
      />,
      {
        width: OG_WIDTH,
        height: OG_HEIGHT,
        fonts: loadedFonts.length > 0 ? loadedFonts : undefined,
      },
    );
  } catch (e: unknown) {
    console.error("OG Persona image generation failed:", e);
    return createErrorResponse();
  }
}
