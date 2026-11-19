import { ImageResponse } from "next/og";
import type { NextRequest } from "next/server";

import { fetchLinkMeta } from "@/features/short-links/utils/linkServerApi";

import {
  colors,
  createErrorResponse,
  fonts,
  getBaseUrl,
  loadFonts,
  OG_HEIGHT,
  OG_WIDTH,
  truncateText,
} from "../lib";

const TITLE_MAX_LENGTH = 90;

/**
 * The generated preview card for a heygaia.link, from what /meta lets anyone
 * see: the real title and kind line for a live public or unlisted link, and
 * the generic "Shared from GAIA" or dead-link copy otherwise.
 */
export async function GET(request: NextRequest) {
  const slug = request.nextUrl.searchParams.get("slug");
  if (!slug) return new Response("Missing slug", { status: 400 });
  try {
    const reply = await fetchLinkMeta(slug, request.headers);
    if (!reply) {
      return new Response("Too many links opened from here", { status: 429 });
    }
    const { meta, cacheControl } = reply;
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
        // The card shows what /meta shows, so it may be kept exactly as long.
        headers: { "Cache-Control": cacheControl ?? "no-store" },
      },
    );
  } catch (error: unknown) {
    console.error("Link OG image generation failed:", error);
    return createErrorResponse();
  }
}
