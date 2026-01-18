import { ImageResponse } from "next/og";
import {
  CategoryBadge,
  colors,
  createErrorResponse,
  createFallbackResponse,
  fetchImageAsBase64,
  fonts,
  getApiBaseUrl,
  getBaseUrl,
  getIconPaths,
  getOgCompatibleAvatarUrl,
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
    const id = searchParams.get("id");

    if (!id) {
      return createFallbackResponse("GAIA Marketplace");
    }

    const apiBaseUrl = getApiBaseUrl();
    const siteBaseUrl = getBaseUrl(request.url);
    const wallpaperUrl = `${siteBaseUrl}${wallpapers.integration.png}`;

    let integration = null;
    try {
      const response = await fetch(`${apiBaseUrl}/integrations/public/${id}`, {
        cache: "no-store",
      });
      if (response.ok) {
        integration = await response.json();
      }
    } catch (e) {
      console.error("[OG Image] Fetch failed:", e);
    }

    const name = integration?.name || id;
    const description = integration?.description || "MCP Integration for GAIA";
    const category = integration?.category || "integration";
    const creatorName = integration?.creator?.name || "Community";
    const rawCreatorAvatar = integration?.creator?.picture; // Note: integration API uses 'picture' not 'avatar'
    const creatorAvatar =
      creatorName !== "Community"
        ? getOgCompatibleAvatarUrl(rawCreatorAvatar)
        : null;

    const cloneCount = integration?.cloneCount || 0;
    const toolCount = integration?.toolCount || 0;

    // Integration ID is used to look up known icons
    const integrationId = integration?.integrationId || id;

    // First, try to get a known icon from the config (same as PublicIntegrationCard)
    const knownIconPath = getOgIconPath(integrationId);
    const iconConfig = getToolIconConfig(integrationId);

    // Get SVG path data from generated file using icon name
    const iconPathData = iconConfig?.icon
      ? getIconPaths(iconConfig.icon)
      : null;

    // If no known icon, try to fetch external icon as base64
    // This allows ICO, SVG, and other formats to be rendered
    let externalIconBase64: string | null = null;
    if (!knownIconPath && !iconPathData && integration?.iconUrl) {
      externalIconBase64 = await fetchImageAsBase64(integration.iconUrl);
    }

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
            zIndex: 1,
          }}
        >
          {/* Only render icon container if we have a valid icon */}
          {(knownIconPath || iconPathData || externalIconBase64) && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                overflow: "hidden",
                flexShrink: 0,
              }}
            >
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
              ) : iconPathData ? (
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
                  <svg
                    width="80"
                    height="80"
                    viewBox={iconPathData.viewBox}
                    fill={iconConfig?.iconColorRaw || "#a1a1aa"}
                  >
                    <title>Integration icon</title>
                    {iconPathData.paths.map((d, i) => (
                      // biome-ignore lint/suspicious/noArrayIndexKey: SVG paths are static and won't reorder
                      <path key={`integration-path-${i}`} d={d} />
                    ))}
                  </svg>
                </div>
              ) : externalIconBase64 ? (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: 120,
                    height: 120,
                    borderRadius: 16,
                    backgroundColor: "#3f3f46",
                  }}
                >
                  {/* biome-ignore lint/performance/noImgElement: og image */}
                  <img
                    src={externalIconBase64}
                    alt="Integration icon"
                    width={100}
                    height={100}
                    style={{ objectFit: "contain" }}
                  />
                </div>
              ) : null}
            </div>
          )}

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
                fontSize: 100,
                fontWeight: 400,
                color: colors.white,
                fontFamily: fonts.serif,
                lineHeight: 1.1,
                textShadow: "0 4px 24px rgba(0,0,0,0.4)",
              }}
            >
              {name}
            </div>

            <div
              style={{
                fontSize: 40,
                color: colors.mutedLight,
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
              justifyContent: "space-between",
              fontFamily: fonts.sans,
              width: "100%",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 40 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                {creatorAvatar ? (
                  /* biome-ignore lint/performance/noImgElement: og image */
                  <img
                    src={creatorAvatar}
                    alt="Creator"
                    width={32}
                    height={32}
                    style={{
                      borderRadius: "50%",
                      objectFit: "cover",
                    }}
                  />
                ) : null}
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

              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {/* GitFork Icon - solid-rounded */}
                <svg
                  width="22"
                  height="22"
                  viewBox="0 0 24 24"
                  fill={colors.mutedLight}
                  role="img"
                  aria-label="Forks"
                >
                  <path
                    d="M6 7C6.55229 7 7 7.44772 7 8C7 8.97108 7.00213 9.59879 7.06431 10.0613C7.12263 10.495 7.21677 10.631 7.2929 10.7071C7.36902 10.7832 7.50497 10.8774 7.93871 10.9357C8.40122 10.9979 9.02893 11 10 11H14C14.9711 11 15.5988 10.9979 16.0613 10.9357C16.495 10.8774 16.631 10.7832 16.7071 10.7071C16.7832 10.631 16.8774 10.495 16.9357 10.0613C16.9979 9.59879 17 8.97108 17 8C17 7.44772 17.4477 7 18 7C18.5523 7 19 7.44772 19 8L19 8.06583C19.0001 8.95232 19.0001 9.71613 18.9179 10.3278C18.8297 10.9833 18.631 11.6117 18.1213 12.1213C17.6117 12.631 16.9833 12.8297 16.3278 12.9179C15.7161 13.0001 14.9523 13.0001 14.0658 13L13 13V16C13 16.5523 12.5523 17 12 17C11.4477 17 11 16.5523 11 16V13H10C9.97799 13 9.95604 13 9.93417 13C9.04769 13.0001 8.28387 13.0001 7.67221 12.9179C7.0167 12.8297 6.38835 12.631 5.87868 12.1213C5.36902 11.6117 5.17028 10.9833 5.08215 10.3278C4.99991 9.71613 4.99995 8.95232 5 8.06583C5 8.04396 5 8.02202 5 8C5 7.44772 5.44772 7 6 7Z"
                    fillRule="evenodd"
                  />
                  <path
                    d="M3.25 6C3.25 4.48122 4.48122 3.25 6 3.25C7.51878 3.25 8.75 4.48122 8.75 6C8.75 7.51878 7.51878 8.75 6 8.75C4.48122 8.75 3.25 7.51878 3.25 6Z"
                    fillRule="evenodd"
                  />
                  <path
                    d="M9.25 18C9.25 16.4812 10.4812 15.25 12 15.25C13.5188 15.25 14.75 16.4812 14.75 18C14.75 19.5188 13.5188 20.75 12 20.75C10.4812 20.75 9.25 19.5188 9.25 18Z"
                    fillRule="evenodd"
                  />
                  <path
                    d="M15.25 6C15.25 4.48122 16.4812 3.25 18 3.25C19.5188 3.25 20.75 4.48122 20.75 6C20.75 7.51878 19.5188 8.75 18 8.75C16.4812 8.75 15.25 7.51878 15.25 6Z"
                    fillRule="evenodd"
                  />
                </svg>
                <span
                  style={{
                    color: colors.mutedLight,
                    fontSize: 24,
                    fontWeight: 400,
                    display: "flex",
                    textShadow: "0 2px 8px rgba(0,0,0,0.4)",
                  }}
                >
                  {cloneCount.toLocaleString()} users
                </span>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {/* PackageOpen Icon - solid-rounded */}
                <svg
                  width="22"
                  height="22"
                  viewBox="0 0 24 24"
                  fill={colors.mutedLight}
                  role="img"
                  aria-label="Tools"
                >
                  <path
                    d="M4.35044 7.774C4.32174 7.79096 4.1703 7.90406 3.98732 8.04259C4.33255 8.2718 4.90262 8.55067 5.72686 8.94271L8.64806 10.3321C10.5147 11.2199 11.239 11.5457 12 11.5457C12.761 11.5457 13.4853 11.2199 15.3519 10.3321L18.2731 8.94271C19.0974 8.55067 19.6674 8.2718 20.0127 8.04258C19.8297 7.90406 19.6783 7.79096 19.6496 7.774C19.331 7.5859 18.8226 7.36842 18.0116 7.02533C17.5253 6.81962 17.3186 6.30224 17.5499 5.86974C17.7812 5.43723 18.3629 5.25338 18.8492 5.45909L18.9153 5.48704C19.6401 5.79361 20.2788 6.06373 20.7281 6.32909C21.174 6.59237 21.75 7.03217 21.75 7.75763L21.75 17.2103C21.75 18.3359 20.9408 19.0901 19.9311 19.7055C18.9125 20.3264 17.2009 21.0608 15.308 21.8729C13.8908 22.4815 12.9743 22.875 12 22.875C11.0257 22.875 10.1092 22.4814 8.69202 21.8729C6.79913 21.0608 5.08751 20.3264 4.0689 19.7055C3.05921 19.0901 2.25 18.3359 2.25 17.2103L2.25 7.75763C2.25 7.03217 2.826 6.59237 3.27186 6.32909C3.72124 6.06372 4.35993 5.79359 5.08479 5.48702L5.15082 5.45909C5.63709 5.25338 6.21879 5.43723 6.45008 5.86974C6.68137 6.30224 6.47466 6.81962 5.98838 7.02534C5.17738 7.36842 4.66899 7.5859 4.35044 7.774ZM6.65435 12.7604C6.28029 12.5825 5.83283 12.7415 5.65491 13.1155C5.477 13.4896 5.63601 13.9371 6.01007 14.115L8.00395 15.0633C8.37801 15.2412 8.82547 15.0822 9.00338 14.7082C9.1813 14.3341 9.02229 13.8866 8.64823 13.7087L6.65435 12.7604Z"
                    fillRule="evenodd"
                  />
                  <path
                    d="M12 1.125C12.5523 1.125 13 1.57272 13 2.125V4.125C13 4.67728 12.5523 5.125 12 5.125C11.4477 5.125 11 4.67728 11 4.125V2.125C11 1.57272 11.4477 1.125 12 1.125ZM7.4 2.325C7.84183 1.99363 8.46863 2.08317 8.8 2.525L10.3 4.525C10.6314 4.96683 10.5418 5.59363 10.1 5.925C9.65817 6.25637 9.03137 6.16683 8.7 5.725L7.2 3.725C6.86863 3.28317 6.95817 2.65637 7.4 2.325ZM16.6 2.325C17.0418 2.65637 17.1314 3.28317 16.8 3.725L15.3 5.725C14.9686 6.16683 14.3418 6.25637 13.9 5.925C13.4582 5.59363 13.3686 4.96683 13.7 4.525L15.2 2.525C15.5314 2.08317 16.1582 1.99363 16.6 2.325Z"
                    fillRule="evenodd"
                  />
                </svg>
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

            <CategoryBadge label={categoryLabel} />
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
