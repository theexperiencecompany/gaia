import { ImageResponse } from "next/og";
import {
  getCategoryInitial,
  getIconPath,
  getOgIconPath,
  getToolIconConfig,
  iconAliases,
  normalizeCategoryName,
  type ToolIconConfig,
  toolIconConfigs,
} from "@/config/toolIconConfig";
import { wallpapers } from "@/config/wallpapers";

// Re-export from shared config
export {
  toolIconConfigs,
  iconAliases,
  normalizeCategoryName,
  getToolIconConfig,
  getIconPath,
  getOgIconPath,
  getCategoryInitial,
  wallpapers,
};
export type { ToolIconConfig };

export const OG_WIDTH = 1200;
export const OG_HEIGHT = 630;

export const colors = {
  background: "#09090b",
  cardBackground: "#18181b",
  border: "#27272a",
  white: "#ffffff",
  muted: "#71717a",
  mutedLight: "#a1a1aa",
  mutedLighter: "#d4d4d8",
  accent: "#60a5fa",
  accentBg: "rgba(59, 130, 246, 0.15)",
} as const;

export const fonts = {
  serif: "Instrument Serif, Georgia, serif",
  sans: "Inter, system-ui, sans-serif",
} as const;

export async function loadGoogleFont(
  font: string,
  text: string
): Promise<ArrayBuffer> {
  const url = `https://fonts.googleapis.com/css2?family=${font}&text=${encodeURIComponent(text)}`;
  const css = await (await fetch(url)).text();
  const resource = css.match(
    /src: url\((.+)\) format\('(opentype|truetype)'\)/
  );

  if (resource) {
    const response = await fetch(resource[1]);
    if (response.status === 200) {
      return await response.arrayBuffer();
    }
  }

  throw new Error("failed to load font data");
}

export async function loadFonts(
  serifText: string,
  sansText: string
): Promise<{ name: string; data: ArrayBuffer; style: "normal" }[]> {
  const fonts: { name: string; data: ArrayBuffer; style: "normal" }[] = [];

  try {
    const [serifFontData, sansFontData] = await Promise.all([
      loadGoogleFont("Instrument+Serif", serifText),
      loadGoogleFont("Inter:wght@300;400;500;600", sansText),
    ]);

    if (serifFontData) {
      fonts.push({
        name: "Instrument Serif",
        data: serifFontData,
        style: "normal",
      });
    }
    if (sansFontData) {
      fonts.push({ name: "Inter", data: sansFontData, style: "normal" });
    }
  } catch {
    // Font loading failed, will use system fallback
  }

  return fonts;
}

export function getBaseUrl(requestUrl: string): string {
  const url = new URL(requestUrl);
  return (
    process.env.NEXT_PUBLIC_BASE_URL ||
    (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : url.origin)
  );
}

export function getApiBaseUrl(): string {
  const apiUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
  return apiUrl.replace(/\/$/, "");
}

export function truncateText(text: string, maxLength: number): string {
  return text.length > maxLength ? text.slice(0, maxLength) + "..." : text;
}

export function formatCount(count: number): string {
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
  return count.toString();
}

export function createFallbackResponse(title: string): ImageResponse {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: colors.background,
        color: colors.white,
        fontSize: 48,
        fontFamily: fonts.sans,
      }}
    >
      {title}
    </div>,
    { width: OG_WIDTH, height: OG_HEIGHT }
  );
}

export function createErrorResponse(): Response {
  return new Response("Failed to generate the image", { status: 500 });
}

export function CategoryBadge({ label }: { label: string }) {
  return (
    <div
      style={{
        backgroundColor: colors.accentBg,
        color: colors.accent,
        padding: "12px 28px",
        borderRadius: 999,
        fontSize: 22,
        fontWeight: 500,
        fontFamily: fonts.sans,
        display: "flex",
      }}
    >
      {label}
    </div>
  );
}

export function CategoryBadgeSmall({ label }: { label: string }) {
  return (
    <div
      style={{
        backgroundColor: colors.accentBg,
        color: colors.accent,
        padding: "8px 20px",
        borderRadius: 999,
        fontSize: 16,
        fontWeight: 500,
      }}
    >
      {label}
    </div>
  );
}

export function HeroLayout({
  title,
  subtitle,
  backgroundImage,
}: {
  title: string;
  subtitle: string;
  backgroundImage: string;
}) {
  return (
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
        src={backgroundImage}
        width={OG_WIDTH}
        height={OG_HEIGHT}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: "bottom",
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
            "linear-gradient(180deg, rgba(9,9,11,0.1) 0%, rgba(9,9,11,0.3) 70%, rgba(9,9,11,0.7) 100%)",
        }}
      />

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          flex: 1,
          padding: 60,
          position: "relative",
          zIndex: 1,
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div
            style={{
              fontSize: 108,
              fontWeight: 400,
              color: colors.white,
              fontFamily: fonts.serif,
              // textShadow: "0 4px 24px rgba(0,0,0,0.4)",
            }}
          >
            {title}
          </div>
          <div
            style={{
              fontSize: 32,
              color: colors.white,
              fontWeight: 500,
              fontFamily: fonts.sans,
              // textShadow: "0 2px 12px rgba(0,0,0,0.4)",
              textAlign: "center",
              maxWidth: 900,
            }}
          >
            {subtitle}
          </div>
        </div>
      </div>
    </div>
  );
}
