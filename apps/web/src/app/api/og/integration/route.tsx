import { ImageResponse } from "next/og";
import {
  CategoryBadge,
  colors,
  createErrorResponse,
  createFallbackResponse,
  fonts,
  getApiBaseUrl,
  getBaseUrl,
  getCategoryInitial,
  getOgCompatibleIconUrl,
  getOgIconPath,
  getToolIconConfig,
  loadFonts,
  OG_HEIGHT,
  OG_WIDTH,
  truncateText,
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
        },
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

    // Integration ID is used to look up known icons
    const integrationId = integration?.integrationId || slug;

    // First, try to get a known icon from the config (same as PublicIntegrationCard)
    const knownIconPath = getOgIconPath(integrationId);
    const iconConfig = getToolIconConfig(integrationId);

    // Then try the external icon URL (converted to OG-compatible format)
    const externalIconUrl = !knownIconPath
      ? getOgCompatibleIconUrl(integration?.iconUrl)
      : null;

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
            alignItems: "flex-start",
            gap: 40,
            padding: "48px 64px",
            position: "relative",
            zIndex: "1",
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
            {/* Priority: 1. Known icon from config, 2. External iconUrl, 3. Category initial fallback */}
            {knownIconPath ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 120,
                  height: 120,
                  borderRadius: 16,
                  backgroundColor: iconConfig?.bgColorRaw || "#3f3f46",
                }}
              >
                {/* biome-ignore lint/performance/noImgElement: og image */}
                <img
                  src={`${siteBaseUrl}${knownIconPath}`}
                  alt="Integration icon"
                  width={100}
                  height={100}
                  style={{ objectFit: "contain" }}
                />
              </div>
            ) : externalIconUrl ? (
              // biome-ignore lint/performance/noImgElement: og image
              <img
                src={externalIconUrl}
                alt="Integration icon"
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
                {getCategoryInitial(name)}
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
      },
    );
  } catch (e: unknown) {
    console.error(`OG Image generation failed:`, e);
    return createErrorResponse();
  }
}
