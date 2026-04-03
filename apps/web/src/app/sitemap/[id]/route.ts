import { NextResponse } from "next/server";

import { ALL_SITEMAP_IDS, getSitemapEntries } from "@/lib/sitemapData";
import { entriesToXml } from "@/lib/sitemapXml";

export async function GET(
  _request: Request,
  props: { params: Promise<{ id: string }> },
) {
  const { id: rawId } = await props.params;
  const id = Number(rawId.replace(/\.xml$/, ""));

  if (!ALL_SITEMAP_IDS.includes(id as (typeof ALL_SITEMAP_IDS)[number])) {
    return new NextResponse("Not Found", { status: 404 });
  }

  const entries = await getSitemapEntries(id);
  const xml = entriesToXml(entries);

  return new NextResponse(xml, {
    headers: {
      "Content-Type": "application/xml",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
