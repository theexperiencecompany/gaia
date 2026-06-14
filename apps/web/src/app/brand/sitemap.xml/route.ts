import { NextResponse } from "next/server";

import { BRAND_IMAGE_ASSETS, BRAND_PAGE_PATH } from "@/lib/brandAssets";
import { getSiteUrl } from "@/lib/seo";
import { escapeXml } from "@/lib/sitemapXml";

/**
 * Image sitemap for the brand / press kit. Surfaces the downloadable logos and
 * wordmarks (referenced from robots.txt) so they are discoverable in image
 * search. Lives outside `[locale]` and is excluded from the i18n middleware by
 * the dotted-path matcher rule.
 */
export async function GET() {
  const baseUrl = getSiteUrl();
  const lastmod = new Date().toISOString();

  const images = BRAND_IMAGE_ASSETS.map((asset) =>
    [
      `    <image:image>`,
      `      <image:loc>${escapeXml(`${baseUrl}${asset.path}`)}</image:loc>`,
      `      <image:title>${escapeXml(asset.title)}</image:title>`,
      `      <image:caption>${escapeXml(asset.caption)}</image:caption>`,
      `    </image:image>`,
    ].join("\n"),
  ).join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url>
    <loc>${escapeXml(`${baseUrl}${BRAND_PAGE_PATH}`)}</loc>
    <lastmod>${lastmod}</lastmod>
${images}
  </url>
</urlset>`;

  return new NextResponse(xml, {
    headers: {
      "Content-Type": "application/xml",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
