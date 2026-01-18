import { ImageResponse } from "next/og";
import type { NextRequest } from "next/server";
import {
  colors,
  createErrorResponse,
  createFallbackResponse,
  fonts,
  formatCount,
  getApiBaseUrl,
  getBaseUrl,
  getCategoryInitial,
  getGaiaTeamLogoUrl,
  getIconPaths,
  getOgCompatibleAvatarUrl,
  getOgIconPath,
  getToolIconConfig,
  isGaiaTeam,
  loadFonts,
  OG_HEIGHT,
  OG_WIDTH,
  truncateText,
  wallpapers,
} from "../shared";

export const runtime = "edge";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const slug = searchParams.get("slug");

    if (!slug) {
      return createFallbackResponse("GAIA Workflows");
    }

    const apiBaseUrl = getApiBaseUrl();
    const siteBaseUrl = getBaseUrl(request.url);
    const wallpaperUrl = `${siteBaseUrl}${wallpapers.useCases.png}`;

    let workflow = null;
    try {
      // First try explore endpoint (has creator info)
      const exploreResponse = await fetch(`${apiBaseUrl}/workflows/explore`, {
        cache: "no-store",
      });
      if (exploreResponse.ok) {
        const data = await exploreResponse.json();
        workflow = data.workflows?.find((w: { id: string }) => w.id === slug);
      }

      // If not in explore, try community endpoint (has creator info)
      if (!workflow) {
        const communityResponse = await fetch(
          `${apiBaseUrl}/workflows/community?limit=100`,
          { cache: "no-store" },
        );
        if (communityResponse.ok) {
          const data = await communityResponse.json();
          workflow = data.workflows?.find((w: { id: string }) => w.id === slug);
        }
      }

      // If still not found, try public endpoint (may not have full creator info)
      if (!workflow) {
        const publicResponse = await fetch(
          `${apiBaseUrl}/workflows/public/${slug}`,
          { cache: "no-store" },
        );
        if (publicResponse.ok) {
          const data = await publicResponse.json();
          workflow = data.workflow;
        }
      }
    } catch (e) {
      console.error("[OG Image] Fetch failed:", e);
    }

    const title = workflow?.title || "GAIA Workflow";
    const description = workflow?.description || "Automate your tasks with AI";
    const steps = workflow?.steps || [];
    const totalExecutions = workflow?.total_executions || 0;

    // Determine if this is a GAIA team workflow
    const creatorId = workflow?.creator?.id;
    const isGaiaTeamWorkflow = isGaiaTeam(creatorId);

    // Use actual creator name, or "GAIA Team" for system workflows
    const creatorName = isGaiaTeamWorkflow
      ? "GAIA Team"
      : workflow?.creator?.name || "Community";

    // Use Experience logo for GAIA team, otherwise use creator avatar (converted to PNG)
    const rawAvatarUrl = workflow?.creator?.avatar;
    const creatorAvatar = isGaiaTeamWorkflow
      ? getGaiaTeamLogoUrl(siteBaseUrl)
      : getOgCompatibleAvatarUrl(rawAvatarUrl);

    const toolCategories = [
      ...new Set(steps.map((s: { category: string }) => s.category)),
    ].slice(0, 3) as string[];

    const truncatedDesc = truncateText(description, 500);

    const loadedFonts = await loadFonts(title, `${title}${truncatedDesc}`);

    return new ImageResponse(
      <div
        tw="flex flex-col w-full h-full relative"
        style={{ fontFamily: fonts.sans }}
      >
        {/* <img
          src={wallpaperUrl}
          width={OG_WIDTH}
          height={OG_HEIGHT}
          tw="absolute inset-0 w-full h-full"
          style={{ objectFit: "cover", objectPosition: "center" }}
        /> */}

        <div
          tw="absolute inset-0"
          style={{
            background:
              "linear-gradient(180deg, rgba(9,9,11,0.1) 0%, rgba(9,9,11,0.3) 50%, rgba(9,9,11,0.5) 100%)",
          }}
        />

        <div tw="flex flex-col flex-1 relative" style={{ zIndex: 10 }}>
          <div
            tw="flex flex-col flex-1 p-14"
            style={{
              backgroundColor: "#18181b",
            }}
          >
            <div tw="flex items-center mb-6" style={{ marginLeft: -6 }}>
              {toolCategories.map((category, index) => {
                const iconConfig = getToolIconConfig(category.toLowerCase());
                const iconPath = getOgIconPath(category.toLowerCase());

                const rotation =
                  toolCategories.length > 1
                    ? index % 2 === 0
                      ? "8deg"
                      : "-8deg"
                    : "0deg";

                if (iconPath && iconConfig) {
                  return (
                    <div
                      key={category}
                      tw="flex items-center justify-center rounded-xl"
                      style={{
                        width: 100,
                        height: 100,
                        backgroundColor: iconConfig.bgColorRaw,
                        transform: `rotate(${rotation})`,
                        marginLeft: index > 0 ? -6 : 0,
                        zIndex: toolCategories.length - index,
                      }}
                    >
                      {/** biome-ignore lint/performance/noImgElement: og image */}
                      <img
                        alt="Icon"
                        src={`${siteBaseUrl}${iconPath}`}
                        width={80}
                        height={80}
                        style={{ objectFit: "contain" }}
                      />
                    </div>
                  );
                }

                const fallbackConfig = iconConfig || {
                  bgColorRaw: "rgba(113, 113, 122, 0.2)",
                  iconColorRaw: "#a1a1aa",
                };

                // Check if we have SVG paths for this category from generated file
                const iconPathData = iconConfig?.icon
                  ? getIconPaths(iconConfig.icon)
                  : null;

                return (
                  <div
                    key={category}
                    tw="flex items-center justify-center rounded-xl"
                    style={{
                      width: 100,
                      height: 100,
                      backgroundColor: fallbackConfig.bgColorRaw,
                      transform: `rotate(${rotation})`,
                      marginLeft: index > 0 ? -6 : 0,
                      zIndex: toolCategories.length - index,
                    }}
                  >
                    {iconPathData ? (
                      <svg
                        width="56"
                        height="56"
                        viewBox={iconPathData.viewBox}
                        fill={fallbackConfig.iconColorRaw}
                      >
                        {iconPathData.paths.map((d, i) => (
                          <path key={`${category}-path-${i}`} d={d} />
                        ))}
                      </svg>
                    ) : (
                      <span
                        tw="text-2xl font-semibold"
                        style={{ color: fallbackConfig.iconColorRaw }}
                      >
                        {getCategoryInitial(category)}
                      </span>
                    )}
                  </div>
                );
              })}
              {toolCategories.length === 0 && (
                <div
                  tw="flex items-center justify-center rounded-xl"
                  style={{
                    width: 100,
                    height: 100,
                    backgroundColor: colors.border,
                  }}
                >
                  <span tw="text-2xl font-semibold text-zinc-400">W</span>
                </div>
              )}
            </div>

            <div
              tw="text-white mb-3"
              style={{
                fontSize: 80,
                fontWeight: 500,
                lineHeight: 1.15,
                fontFamily: fonts.serif,
              }}
            >
              {title}
            </div>

            <div
              tw="flex-1 mb-6"
              style={{
                fontSize: 28,
                color: colors.mutedLight,
                lineHeight: 1.5,
              }}
            >
              {truncatedDesc}
            </div>

            <div tw="flex items-center justify-between">
              <div tw="flex items-center">
                {creatorAvatar ? (
                  // biome-ignore lint/performance/noImgElement: og image
                  <img
                    src={creatorAvatar}
                    alt="Creator Avatar"
                    width={40}
                    height={40}
                    tw={`${!isGaiaTeamWorkflow ? "rounded-full" : ""} `}
                    style={{
                      objectFit: !isGaiaTeamWorkflow ? "cover" : "contain",
                    }}
                  />
                ) : (
                  <div
                    tw="flex items-center justify-center rounded-full text-lg font-semibold"
                    style={{
                      width: 40,
                      height: 40,
                      backgroundColor: colors.border,
                      color: colors.mutedLight,
                    }}
                  >
                    {creatorName.charAt(0).toUpperCase()}
                  </div>
                )}
                <span tw="ml-3 text-xl" style={{ color: colors.mutedLight }}>
                  by {creatorName}
                </span>
              </div>

              <div tw="flex items-center">
                {totalExecutions > 0 && (
                  <div tw="flex items-center" style={{ color: colors.muted }}>
                    <svg
                      width="22"
                      height="22"
                      viewBox="0 0 24 24"
                      fill="currentColor"
                    >
                      <polygon points="5 3 19 12 5 21 5 3" />
                    </svg>
                    <span tw="ml-2 text-xl">
                      {formatCount(totalExecutions)} runs
                    </span>
                  </div>
                )}
              </div>
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
    console.error("OG Image generation failed:", e);
    return createErrorResponse();
  }
}
