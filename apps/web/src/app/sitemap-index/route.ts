import { NextResponse } from "next/server";

import { getSiteUrl } from "@/lib/seo";

/**
 * Sitemap IDs must match those in sitemap.ts
 */
const SITEMAP_IDS = [0, 1, 2, 3, 4];

/**
 * Route handler for the root sitemap index.
 * This generates an XML sitemap index that points to all child sitemaps
 * created by generateSitemaps() in sitemap.ts.
 */
export async function GET() {
  const baseUrl = getSiteUrl();

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${SITEMAP_IDS.map(
  (id) => `  <sitemap>
    <loc>${baseUrl}/sitemap/${id}.xml</loc>
  </sitemap>`,
).join("\n")}
</sitemapindex>`;

  return new NextResponse(xml, {
    headers: {
      "Content-Type": "application/xml",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
