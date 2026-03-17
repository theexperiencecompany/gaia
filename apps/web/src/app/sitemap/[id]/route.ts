import type { MetadataRoute } from "next";
import { NextResponse } from "next/server";

import { generateSitemaps, getSitemapEntries } from "@/app/sitemap-data";

/**
 * Serialize sitemap entries to XML with correct element ordering.
 *
 * The sitemap XSD requires elements in strict order:
 *   loc -> lastmod -> changefreq -> priority -> <any namespace>
 *
 * Next.js's built-in MetadataRoute serializer puts xhtml:link (alternates)
 * BEFORE lastmod, which violates the XSD schema and causes validation
 * failures in Google Search Console and other parsers.
 *
 * This route handler generates the XML directly with correct ordering.
 */
function entriesToXml(entries: MetadataRoute.Sitemap): string {
  const hasAlternates = entries.some((e) => e.alternates?.languages);
  const nsAttr = hasAlternates
    ? ' xmlns:xhtml="http://www.w3.org/1999/xhtml"'
    : "";

  const urlElements = entries
    .map((entry) => {
      const parts: string[] = [`<loc>${entry.url}</loc>`];

      if (entry.lastModified) {
        const date =
          entry.lastModified instanceof Date
            ? entry.lastModified.toISOString()
            : String(entry.lastModified);
        parts.push(`<lastmod>${date}</lastmod>`);
      }

      // xhtml:link elements MUST come after loc/lastmod/changefreq/priority
      if (entry.alternates?.languages) {
        for (const [lang, href] of Object.entries(entry.alternates.languages)) {
          parts.push(
            `<xhtml:link rel="alternate" hreflang="${lang}" href="${href}" />`,
          );
        }
      }

      return `<url>\n${parts.map((p) => `  ${p}`).join("\n")}\n</url>`;
    })
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"${nsAttr}>\n${urlElements}\n</urlset>`;
}

export async function generateStaticParams() {
  const sitemaps = await generateSitemaps();
  return sitemaps.map((s) => ({ id: String(s.id) }));
}

export async function GET(
  _request: Request,
  props: { params: Promise<{ id: string }> },
) {
  const { id } = await props.params;
  const sitemapId = Number(id);

  const entries = await getSitemapEntries(sitemapId);
  const xml = entriesToXml(entries);

  return new NextResponse(xml, {
    headers: {
      "Content-Type": "application/xml",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
