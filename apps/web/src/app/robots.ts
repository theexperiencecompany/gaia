import type { MetadataRoute } from "next";

import { siteConfig } from "@/lib/seo";

/**
 * Generate robots.txt for GAIA
 * Controls search engine crawling and indexing
 */
export default function robots(): MetadataRoute.Robots {
  const baseUrl = siteConfig.url;

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
