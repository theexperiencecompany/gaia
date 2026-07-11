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
    const wallpaperUrl = `${siteBaseUrl}${wallpapers.useCases.png}`;

    let persona: OgPersona | null = null;
    try {
      // Persona entries are public static assets — fetch straight from the site.
      const response = await fetch(`${siteBaseUrl}/data/personas/${slug}.json`, {
        cache: "no-store",
      });
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
      persona.metaDescription ?? "Workflows tuned for your job, not generic ones.",
      160,
    );
    const allText = `${title}${description}heygaia.io`;

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
              fontSize: 88,
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
            {description}
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
    console.error("OG Persona image generation failed:", e);
    return createErrorResponse();
  }
}
