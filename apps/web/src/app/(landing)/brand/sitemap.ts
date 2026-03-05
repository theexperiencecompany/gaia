import type { MetadataRoute } from "next";

import { getSiteUrl } from "@/lib/seo";

/**
 * Image sitemap for brand assets
 * This helps Google Images index our brand assets properly
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = getSiteUrl();

  const brandImages = [
    "experience_full_wordmark_black.png",
    "experience_full_wordmark_white.png",
    "experience_logo_black.png",
    "experience_logo_black.svg",
    "experience_logo_white.png",
    "experience_logo_white.svg",
    "experience_wordmark_black.png",
    "experience_wordmark_white.png",
    "gaia_logo.png",
    "gaia_logo.svg",
    "gaia_wordmark_black.png",
    "gaia_wordmark_white.png",
  ];

  return brandImages.map((image) => ({
    url: `${baseUrl}/brand/${image}`,
    changeFrequency: "yearly",
    priority: 0.8,
  }));
}
