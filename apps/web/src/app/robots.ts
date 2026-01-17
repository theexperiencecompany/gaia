import type { MetadataRoute } from "next";

/**
 * Generate robots.txt for GAIA
 * Controls search engine crawling and indexing
 */
export default function robots(): MetadataRoute.Robots {
  const baseUrl = "https://heygaia.io";

  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/api/og/*"],
        disallow: ["/api/"],
      },
    ],
    sitemap: `${baseUrl}/sitemap.xml`,
  };
}
