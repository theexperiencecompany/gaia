import { ImageResponse } from "next/og";
import type { NextRequest } from "next/server";

import { internalApiHeaders } from "@/lib/internalApiHeaders";
import type { LinkPreviewMeta } from "@/types/features/shortLinkTypes";

import {
  colors,
  createErrorResponse,
  fonts,
  getApiBaseUrl,
  getBaseUrl,
  loadFonts,
  OG_HEIGHT,
  OG_WIDTH,
  truncateText,
} from "../lib";

// Previews are re-fetched by chat apps; a revoked link shows the dead card within this window.
const LINK_CARD_CACHE_CONTROL = "public, max-age=300";
const TITLE_MAX_LENGTH = 90;

async function fetchLinkMeta(
  slug: string,
  viewer: Headers,
): Promise<LinkPreviewMeta> {
  const response = await fetch(
    `${getApiBaseUrl()}/l/${encodeURIComponent(slug)}/meta`,
    { cache: "no-store", headers: internalApiHeaders(viewer) },
  );
  if (!response.ok) {
    // Never the slug: it is a working link, and this message reaches Sentry.
    throw new Error(`Short link meta failed with ${response.status}`);
  }
  return (await response.json()) as LinkPreviewMeta;
}

/**
 * The generated preview card for a heygaia.link, from what /meta lets anyone
 * see: the real title and kind line for a live public or unlisted link, and
 * the generic "Shared from GAIA" or dead-link copy otherwise.
 */
export async function GET(request: NextRequest) {
  const slug = request.nextUrl.searchParams.get("slug");
  if (!slug) return new Response("Missing slug", { status: 400 });
  try {
    const meta = await fetchLinkMeta(slug, request.headers);
    const title = truncateText(meta.title, TITLE_MAX_LENGTH);
    const logoUrl = `${getBaseUrl(request.url)}/brand/gaia_logo.png`;
    const loadedFonts = await loadFonts("", `${title}${meta.description}GAIA`);

    return new ImageResponse(
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 72,
          backgroundColor: colors.background,
          fontFamily: fonts.sans,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {/* biome-ignore lint/performance/noImgElement: Satori renders plain img, not next/image */}
          <img src={logoUrl} alt="" width={56} height={56} />
          <div style={{ display: "flex", fontSize: 32, color: colors.white }}>
            GAIA
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div
            style={{
              display: "flex",
              fontSize: 64,
              fontWeight: 500,
              lineHeight: 1.1,
              color: colors.white,
            }}
          >
            {title}
          </div>
          <div
            style={{ display: "flex", fontSize: 30, color: colors.mutedLight }}
          >
            {meta.description}
          </div>
        </div>
      </div>,
      {
        width: OG_WIDTH,
        height: OG_HEIGHT,
        fonts: loadedFonts.length > 0 ? loadedFonts : undefined,
        headers: { "Cache-Control": LINK_CARD_CACHE_CONTROL },
      },
    );
  } catch (error: unknown) {
    console.error("Link OG image generation failed:", error);
    return createErrorResponse();
  }
}
