import { ImageResponse } from "next/og";
import { getIconPaths } from "@/config/iconPaths.generated";
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
  getIconPaths,
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
  accent: "#00bbff",
  accentBg: "#00bbff50",
} as const;

export const fonts = {
  serif: "Instrument Serif, Georgia, serif",
  sans: "Inter, system-ui, sans-serif",
} as const;

export async function loadGoogleFont(
  font: string,
  text: string,
): Promise<ArrayBuffer> {
  const url = `https://fonts.googleapis.com/css2?family=${font}&text=${encodeURIComponent(text)}`;
  const css = await (await fetch(url)).text();
  const resource = css.match(
    /src: url\((.+)\) format\('(opentype|truetype)'\)/,
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
  sansText: string,
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
    { width: OG_WIDTH, height: OG_HEIGHT },
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
        backdropFilter: "blur(5px)",
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
          zIndex: "1",
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

/**
 * OG-compatible image formats (Satori doesn't support WebP)
 */
const OG_COMPATIBLE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".svg", ".gif"];

/**
 * Check if a URL points to an OG-compatible image format
 */
export function isOgCompatibleUrl(url: string): boolean {
  if (!url) return false;
  const lowercaseUrl = url.toLowerCase();
  return OG_COMPATIBLE_EXTENSIONS.some((ext) => lowercaseUrl.includes(ext));
}

/**
 * Get an OG-compatible avatar URL
 * - GitHub avatars: append format parameter for PNG
 * - Gravatar: append format parameter for PNG
 * - Other URLs: return as-is if compatible, null otherwise
 */
export function getOgCompatibleAvatarUrl(
  url: string | null | undefined,
): string | null {
  if (!url) return null;

  // GitHub avatar URLs - force PNG format
  if (
    url.includes("avatars.githubusercontent.com") ||
    url.includes("github.com")
  ) {
    const avatarUrl = new URL(url);
    avatarUrl.searchParams.set("format", "png");
    return avatarUrl.toString();
  }

  // Gravatar URLs - force PNG format
  if (url.includes("gravatar.com") || url.includes("secure.gravatar.com")) {
    const gravatarUrl = url.includes("?") ? `${url}&f=png` : `${url}?f=png`;
    return gravatarUrl.replace(".jpg", ".png");
  }

  // Google user content (profile pics)
  if (url.includes("googleusercontent.com")) {
    return url;
  }

  // WorkOS CDN (Clerk/AuthKit profile pics)
  if (url.includes("workoscdn.com")) {
    return url;
  }

  // Clerk CDN (clerk.dev profile pics)
  if (url.includes("clerk.dev") || url.includes("clerk.com")) {
    return url;
  }

  // Check if already OG-compatible
  if (isOgCompatibleUrl(url)) {
    return url;
  }

  // WebP or unknown format - can't use
  return null;
}

/**
 * Get an OG-compatible icon URL for integrations
 * Validates the URL format and returns null for incompatible formats
 */
export function getOgCompatibleIconUrl(
  url: string | null | undefined,
): string | null {
  if (!url) return null;

  const lowercaseUrl = url.toLowerCase();

  // Skip WebP images - Satori doesn't support them
  if (lowercaseUrl.endsWith(".webp")) {
    return null;
  }

  // Skip ICO images - Satori doesn't support them
  if (lowercaseUrl.includes(".ico")) {
    return null;
  }

  // Skip external SVG images - fetching is unreliable (rate limits, CORS)
  // Note: local SVG paths (starting with /) are handled separately via svgPath in iconConfig
  if (lowercaseUrl.includes(".svg")) {
    return null;
  }

  // Extract path without query string for extension checking
  const urlPath = lowercaseUrl.split("?")[0];

  // Check if compatible format (png, jpg, jpeg, gif only - others are skipped above)
  const compatibleExtensions = [".png", ".jpg", ".jpeg", ".gif"];
  if (compatibleExtensions.some((ext) => urlPath.endsWith(ext))) {
    return url;
  }

  // Also check if the URL contains these extensions anywhere (for dynamic URLs)
  if (compatibleExtensions.some((ext) => lowercaseUrl.includes(ext))) {
    return url;
  }

  return null;
}

/**
 * Fetch any external image and convert to base64 data URI
 * This allows Satori to render images it normally can't handle (external SVG, etc)
 * Works on Edge runtime without requiring heavy dependencies like Sharp
 *
 * Note: ICO files are NOT supported - Satori cannot render them even as base64.
 * Changing MIME type doesn't convert the binary format.
 */
export async function fetchImageAsBase64(url: string): Promise<string | null> {
  try {
    // Skip ICO files upfront - Satori cannot render them
    const lowercaseUrl = url.toLowerCase();
    if (lowercaseUrl.includes(".ico")) {
      console.log(`[OG Image] Skipping ICO file (unsupported): ${url}`);
      return null;
    }

    const response = await fetch(url, {
      headers: {
        Accept: "image/*",
        "User-Agent": "Mozilla/5.0 (compatible; GAIA-OG/1.0)",
      },
    });

    if (!response.ok) {
      console.warn(
        `[OG Image] Failed to fetch image: ${url} (${response.status})`,
      );
      return null;
    }

    const contentType = response.headers.get("content-type") || "image/png";
    const mimeType = contentType.split(";")[0].trim();

    // Skip ICO files detected by content-type - Satori cannot render them
    if (
      mimeType === "image/x-icon" ||
      mimeType === "image/vnd.microsoft.icon"
    ) {
      console.log(
        `[OG Image] Skipping ICO file (unsupported content-type): ${url}`,
      );
      return null;
    }

    const arrayBuffer = await response.arrayBuffer();
    const base64 = Buffer.from(arrayBuffer).toString("base64");

    return `data:${mimeType};base64,${base64}`;
  } catch (error) {
    console.error(`[OG Image] Error fetching image as base64:`, error);
    return null;
  }
}

/**
 * Check if a URL points to an SVG file
 */
export function isSvgUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  const lowercaseUrl = url.toLowerCase();
  return lowercaseUrl.includes(".svg");
}

/**
 * Fetch external SVG content and extract the path data for inline rendering
 * Returns the viewBox and path data, or null if fetch fails
 */
export async function fetchSvgContent(
  url: string,
): Promise<{ viewBox: string; paths: string[] } | null> {
  try {
    console.log("[OG Image] Fetching SVG from:", url);
    const response = await fetch(url, {
      headers: {
        Accept: "image/svg+xml",
      },
    });

    console.log("[OG Image] SVG fetch response:", {
      ok: response.ok,
      status: response.status,
      contentType: response.headers.get("content-type"),
    });

    if (!response.ok) return null;

    const svgText = await response.text();
    console.log("[OG Image] SVG content length:", svgText.length);
    console.log("[OG Image] SVG preview:", svgText.substring(0, 500));

    // Extract viewBox attribute
    const viewBoxMatch = svgText.match(/viewBox=["']([^"']+)["']/i);
    const viewBox = viewBoxMatch?.[1] || "0 0 24 24";

    // Extract path d attributes
    const pathMatches = svgText.matchAll(
      /<path[^>]*d=["']([^"']+)["'][^>]*>/gi,
    );
    const paths: string[] = [];
    for (const match of pathMatches) {
      if (match[1]) {
        paths.push(match[1]);
      }
    }

    console.log("[OG Image] Extracted paths count:", paths.length);

    // If no paths found, return null and let fallback handle it
    if (paths.length === 0) {
      console.log("[OG Image] No paths found in SVG, using fallback");
      return null;
    }

    return { viewBox, paths };
  } catch (error) {
    console.error("[OG Image] Failed to fetch SVG:", error);
    return null;
  }
}

/**
 * Check if the creator is the GAIA team (system user)
 */
export function isGaiaTeam(creatorId: string | null | undefined): boolean {
  return !creatorId || creatorId === "system";
}

/**
 * Get the GAIA team / Experience company logo path for OG images
 */
export function getGaiaTeamLogoUrl(siteBaseUrl: string): string {
  return `${siteBaseUrl}/brand/experience_logo_white.png`;
}
