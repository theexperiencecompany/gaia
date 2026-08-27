import { ImageResponse } from "next/og";
import { createElement } from "react";
import { siteConfig } from "@/lib/seo";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

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
  const cssResponse = await fetch(url);
  if (!cssResponse.ok) {
    throw new Error(`failed to load font stylesheet (${cssResponse.status})`);
  }
  const css = await cssResponse.text();
  const resource = css.match(
    /src: url\((.+)\) format\('(opentype|truetype)'\)/,
  );

  if (resource) {
    const fontResponse = await fetch(resource[1]);
    if (fontResponse.status === 200) {
      return await fontResponse.arrayBuffer();
    }
  }

  throw new Error("failed to load font data");
}

export async function loadFonts(
  serifText: string,
  sansText: string,
): Promise<{ name: string; data: ArrayBuffer; style: "normal" }[]> {
  const loaded: { name: string; data: ArrayBuffer; style: "normal" }[] = [];

  try {
    const [serifFontData, sansFontData] = await Promise.all([
      loadGoogleFont("Instrument+Serif", serifText),
      loadGoogleFont("Inter:wght@300;400;500;600", sansText),
    ]);

    if (serifFontData) {
      loaded.push({
        name: "Instrument Serif",
        data: serifFontData,
        style: "normal",
      });
    }
    if (sansFontData) {
      loaded.push({ name: "Inter", data: sansFontData, style: "normal" });
    }
  } catch {
    // Font loading failed, will use system fallback
  }

  return loaded;
}

export function getBaseUrl(_requestUrl: string): string {
  return siteConfig.url;
}

export function getApiBaseUrl(): string {
  return getServerApiBaseUrl() ?? "";
}

export function truncateText(text: string, maxLength: number): string {
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

export function formatCount(count: number): string {
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
  return count.toString();
}

export function createFallbackResponse(title: string): ImageResponse {
  // Built with createElement (not JSX) so this response factory can live in a
  // plain .ts module alongside the other OG helpers instead of a component file.
  return new ImageResponse(
    createElement(
      "div",
      {
        style: {
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: colors.background,
          color: colors.white,
          fontSize: 48,
          fontFamily: fonts.sans,
        },
      },
      title,
    ),
    { width: OG_WIDTH, height: OG_HEIGHT },
  );
}

export function createErrorResponse(): Response {
  return new Response("Failed to generate the image", { status: 500 });
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
      return null;
    }

    const response = await fetch(url, {
      headers: {
        Accept: "image/*",
        "User-Agent": "Mozilla/5.0 (compatible; GAIA-OG/1.0)",
      },
    });

    if (!response.ok) {
      return null;
    }

    const contentType = response.headers.get("content-type") || "image/png";
    const mimeType = contentType.split(";")[0].trim();

    if (
      mimeType === "image/x-icon" ||
      mimeType === "image/vnd.microsoft.icon"
    ) {
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
