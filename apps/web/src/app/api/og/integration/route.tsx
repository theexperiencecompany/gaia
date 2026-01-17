import { ImageResponse } from "next/og";
import {
  colors,
  fonts,
  loadFonts,
  getApiBaseUrl,
  getBaseUrl,
  truncateText,
  createFallbackResponse,
  createErrorResponse,
  CategoryBadge,
  OG_WIDTH,
  OG_HEIGHT,
  wallpapers,
} from "../shared";

export const runtime = "edge";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const slug = searchParams.get("slug");

    if (!slug) {
      return createFallbackResponse("GAIA Marketplace");
    }

    const apiBaseUrl = getApiBaseUrl();
    const siteBaseUrl = getBaseUrl(request.url);
    const wallpaperUrl = `${siteBaseUrl}${wallpapers.integration.png}`;

    let integration = null;
    try {
      const response = await fetch(
        `${apiBaseUrl}/integrations/public/${slug}`,
        {
          cache: "no-store",
        }
      );
      if (response.ok) {
        integration = await response.json();
      }
    } catch (e) {
      console.error("[OG Image] Fetch failed:", e);
    }

    const name = integration?.name || slug;
    const description = integration?.description || "MCP Integration for GAIA";
    const category = integration?.category || "integration";
    const creatorName = integration?.creator?.name || "Community";
    const cloneCount = integration?.cloneCount || 0;
    const toolCount = integration?.toolCount || 0;
    const iconUrl = integration?.iconUrl;

    const categoryLabel =
      category.charAt(0).toUpperCase() + category.slice(1).toLowerCase();
    const truncatedDesc = truncateText(description, 140);

    const allText = `${name}${truncatedDesc}${categoryLabel}by ${creatorName}${cloneCount} clones${toolCount} toolsGAIA`;
    const loadedFonts = await loadFonts(name, allText);

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
        <img
          src={wallpaperUrl}
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
            alignItems: "flex-start",
            gap: 40,
            padding: "48px 64px",
            position: "relative",
            zIndex: 1,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              overflow: "hidden",
              flexShrink: 0,
            }}
          >
            {iconUrl ? (
              <img
                src={iconUrl}
                width={120}
                height={120}
                style={{ objectFit: "contain" }}
              />
            ) : (
              <div
                style={{
                  fontSize: 64,
                  fontWeight: 600,
                  color: colors.mutedLight,
                  fontFamily: fonts.sans,
                  display: "flex",
                }}
              >
                {name.charAt(0).toUpperCase()}
              </div>
            )}
          </div>

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              flex: 1,
              gap: 16,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 24,
                flexWrap: "wrap",
              }}
            >
              <div
                style={{
                  fontSize: 72,
                  fontWeight: 400,
                  color: colors.white,
                  fontFamily: fonts.serif,
                  lineHeight: 1.1,
                  textShadow: "0 4px 24px rgba(0,0,0,0.4)",
                }}
              >
                {name}
              </div>
              <CategoryBadge label={categoryLabel} />
            </div>

            <div
              style={{
                fontSize: 32,
                color: colors.mutedLighter,
                lineHeight: 1.45,
                fontFamily: fonts.sans,
                fontWeight: 100,
                maxWidth: 820,
                display: "flex",
                textShadow: "0 2px 8px rgba(0,0,0,0.4)",
              }}
            >
              {truncatedDesc}
            </div>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 40,
              fontFamily: fonts.sans,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span
                style={{
                  color: colors.mutedLight,
                  fontSize: 24,
                  fontWeight: 400,
                  display: "flex",
                  textShadow: "0 2px 8px rgba(0,0,0,0.4)",
                }}
              >
                by {creatorName}
              </span>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span
                style={{
                  color: colors.mutedLight,
                  fontSize: 24,
                  fontWeight: 400,
                  display: "flex",
                  textShadow: "0 2px 8px rgba(0,0,0,0.4)",
                }}
              >
                {cloneCount.toLocaleString()} clones
              </span>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span
                style={{
                  color: colors.mutedLight,
                  fontSize: 24,
                  fontWeight: 400,
                  display: "flex",
                  textShadow: "0 2px 8px rgba(0,0,0,0.4)",
                }}
              >
                {toolCount} tools
              </span>
            </div>
          </div>
        </div>
      </div>,
      {
        width: OG_WIDTH,
        height: OG_HEIGHT,
        fonts: loadedFonts.length > 0 ? loadedFonts : undefined,
      }
    );
  } catch (e: unknown) {
    console.error(`OG Image generation failed:`, e);
    return createErrorResponse();
  }
}
