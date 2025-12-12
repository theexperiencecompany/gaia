import type { MetadataRoute } from "next";

/**
 * Image sitemap for brand assets
 * This helps Google Images index our brand assets properly
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = "https://heygaia.io";

  const brandImages = [
    "gaia-logo-blue.svg",
    "gaia-wordmark-black.svg",
    "gaia-wordmark-white.svg",
    "logo-white.svg",
    "logo-black.svg",
    "logo-experience-white.svg",
    "logo-experience-black.svg",
    "logo-wordmark-white.svg",
    "logo-wordmark-black.svg",
    "text-experience-white.svg",
    "text-experience-black.svg",
    "text-full-white.svg",
    "text-full-black.svg",
  ];

  return brandImages.map((image) => ({
    url: `${baseUrl}/brand/${image}`,
    lastModified: new Date(),
    changeFrequency: "yearly",
    priority: 0.8,
  }));
}
