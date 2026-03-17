import type { MetadataRoute } from "next";

function escapeXml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function formatDate(date: string | Date | undefined): string {
  if (!date) return "";
  const d = date instanceof Date ? date : new Date(date);
  return d.toISOString();
}

/**
 * Serialize sitemap entries into XML.
 */
export function entriesToXml(entries: MetadataRoute.Sitemap): string {
  const urls = entries
    .map((entry) => {
      const parts: string[] = [];
      parts.push(`  <url>`);
      parts.push(`    <loc>${escapeXml(entry.url)}</loc>`);

      if (entry.lastModified) {
        parts.push(`    <lastmod>${formatDate(entry.lastModified)}</lastmod>`);
      }
      if (entry.changeFrequency) {
        parts.push(`    <changefreq>${entry.changeFrequency}</changefreq>`);
      }
      if (entry.priority !== undefined) {
        parts.push(`    <priority>${entry.priority}</priority>`);
      }

      if (entry.alternates?.languages) {
        for (const [lang, href] of Object.entries(entry.alternates.languages)) {
          if (href) {
            parts.push(
              `    <xhtml:link rel="alternate" hreflang="${escapeXml(lang)}" href="${escapeXml(href)}" />`,
            );
          }
        }
      }

      parts.push(`  </url>`);
      return parts.join("\n");
    })
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n${urls}\n</urlset>`;
}

/**
 * Serialize a sitemap index into XML.
 */
export function sitemapIndexToXml(
  sitemapUrls: Array<{ loc: string; lastmod?: string }>,
): string {
  const sitemaps = sitemapUrls
    .map((s) => {
      const parts = [`  <sitemap>`, `    <loc>${escapeXml(s.loc)}</loc>`];
      if (s.lastmod) {
        parts.push(`    <lastmod>${s.lastmod}</lastmod>`);
      }
      parts.push(`  </sitemap>`);
      return parts.join("\n");
    })
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${sitemaps}\n</sitemapindex>`;
}
