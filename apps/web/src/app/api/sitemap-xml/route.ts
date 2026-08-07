import { NextResponse } from "next/server";

import { getSiteUrl } from "@/lib/seo";
import { ALL_SITEMAP_IDS } from "@/lib/sitemapData";
import { sitemapIndexToXml } from "@/lib/sitemapXml";

export async function GET() {
  const baseUrl = getSiteUrl();

  // No lastmod: stamping the request time on every segment is a fake
  // freshness signal that Google detects and ignores. Omitting it is honest.
  const sitemapUrls = ALL_SITEMAP_IDS.map((id) => ({
    loc: `${baseUrl}/sitemap/${id}.xml`,
  }));

  const xml = sitemapIndexToXml(sitemapUrls);

  return new NextResponse(xml, {
    headers: {
      "Content-Type": "application/xml",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
