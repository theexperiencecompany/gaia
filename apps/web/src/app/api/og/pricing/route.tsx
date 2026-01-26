import { ImageResponse } from "next/og";
import {
  createErrorResponse,
  getBaseUrl,
  HeroLayout,
  loadFonts,
  OG_HEIGHT,
  OG_WIDTH,
  wallpapers,
} from "../shared";

export const runtime = "edge";

export async function GET(request: Request) {
  try {
    const baseUrl = getBaseUrl(request.url);
    const wallpaperUrl = `${baseUrl}${wallpapers.pricing.png}`;

    const title = "Pricing";
    const subtitle = "Choose the plan that matches your ambition";

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
