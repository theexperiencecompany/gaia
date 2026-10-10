import { ImageResponse } from "next/og";
import { wallpapers } from "@/config/wallpapers";
import {
  createErrorResponse,
  getBaseUrl,
  loadFonts,
  OG_HEIGHT,
  OG_WIDTH,
} from "../lib";
import { HeroLayout } from "../shared";

export const runtime = "edge";

export async function GET(request: Request) {
  try {
    const baseUrl = getBaseUrl(request.url);
    const wallpaperUrl = `${baseUrl}${wallpapers.integration.png}`;

    const title = "Integrations";
    const subtitle =
      "Discover and connect powerful MCP integrations to supercharge your workflow";

    const loadedFonts = await loadFonts(title, `${title}${subtitle}`);

    return new ImageResponse(
      <HeroLayout
        title={title}
        subtitle={subtitle}
        backgroundImage={wallpaperUrl}
      />,
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
