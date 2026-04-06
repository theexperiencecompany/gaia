import { createHash } from "node:crypto";
import { NextResponse } from "next/server";
import type { Release, ReleasesResponse } from "@/features/whats-new/types";

export const revalidate = 60;

const RSS_URL = "https://docs.heygaia.io/release-notes/rss.xml";

function extractTag(xml: string, tag: string): string {
  // Escape colons for regex safety (e.g. "content:encoded")
  const escaped = tag.replace(/:/g, "\\:");
  const cdataMatch = xml.match(
    new RegExp(
      `<${escaped}[^>]*><!\\[CDATA\\[([\\s\\S]*?)\\]\\]><\\/${escaped}>`,
    ),
  );
  if (cdataMatch) return cdataMatch[1].trim();

  const plainMatch = xml.match(
    new RegExp(`<${escaped}[^>]*>([\\s\\S]*?)<\\/${escaped}>`),
  );
  return plainMatch ? plainMatch[1].trim() : "";
}

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

function decodeEntities(input: string): string {
  return input
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) =>
      String.fromCodePoint(parseInt(hex, 16)),
    )
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&([a-zA-Z]+);/g, (m, name) => NAMED_ENTITIES[name] ?? m);
}

function stripTags(html: string): string {
  return decodeEntities(html.replace(/<[^>]+>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function parseRssItem(itemXml: string): Release | null {
  const label = extractTag(itemXml, "title"); // e.g. "Feb 27, 2026"
  const content = extractTag(itemXml, "content:encoded");
  const link = extractTag(itemXml, "link");
  const guid = extractTag(itemXml, "guid");

  if (!content) return null;

  // First <h1> is the real release title
  const h1Match = content.match(/<h1[^>]*>([\s\S]*?)<\/h1>/);
  const title = h1Match ? stripTags(h1Match[1]) : label;

  // Body = content without the leading H1
  let body = h1Match
    ? content.replace(/<h1[^>]*>[\s\S]*?<\/h1>\s*/, "")
    : content;

  // Extract first image as hero, remove from body
  const imageMatch = body.match(/<img[^>]+src="([^"]+)"/);
  const imageUrl = imageMatch ? imageMatch[1] : null;
  body = body.replace(/<img[^>]+\/?>/g, "").trim();

  // Plain-text summary from first paragraph
  const paraMatch = body.match(/<p[^>]*>([\s\S]*?)<\/p>/);
  const summary = paraMatch
    ? stripTags(paraMatch[1]).slice(0, 200)
    : stripTags(body).slice(0, 200) || title;

  // Date: parse from the item <title> (the label) — Mintlify's <pubDate>
  // is the build time, not the release date.
  const parsed = label ? new Date(label) : null;
  const date =
    parsed && !Number.isNaN(parsed.getTime())
      ? parsed.toISOString()
      : new Date().toISOString();

  const id = createHash("sha1")
    .update(guid || link || `${label}-${title}`)
    .digest("hex")
    .slice(0, 12);

  // Extract affected apps from h2 headers (e.g. "<h2><a>API v0.16.0</a></h2>")
  const KNOWN_APPS = [
    "API",
    "Web",
    "Desktop",
    "Mobile",
    "CLI",
    "Voice Agent",
    "Discord",
    "Slack",
    "Telegram",
  ];
  const h2Texts = [...body.matchAll(/<h2[^>]*>([\s\S]*?)<\/h2>/g)].map((m) =>
    stripTags(m[1]),
  );
  const appsTouched = KNOWN_APPS.filter((app) =>
    h2Texts.some((text) => text.toLowerCase().startsWith(app.toLowerCase())),
  );

  return {
    id,
    title,
    date,
    summary,
    html: body,
    imageUrl,
    appsTouched,
    docsUrl: link || "https://docs.heygaia.io/release-notes",
  };
}

function parseRss(xml: string): Release[] {
  const items = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)];
  return items
    .map((m) => parseRssItem(m[1]))
    .filter((r): r is Release => r !== null);
}

export async function GET() {
  const response = await fetch(RSS_URL, {
    headers: { Accept: "application/rss+xml, application/xml, text/xml" },
    next: { revalidate: 60 },
  });

  if (!response.ok) {
    return NextResponse.json(
      {
        releases: [],
        fetchedAt: new Date().toISOString(),
      } satisfies ReleasesResponse,
      { status: 502 },
    );
  }

  const xml = await response.text();
  const releases = parseRss(xml);

  return NextResponse.json({
    releases,
    fetchedAt: new Date().toISOString(),
  } satisfies ReleasesResponse);
}
