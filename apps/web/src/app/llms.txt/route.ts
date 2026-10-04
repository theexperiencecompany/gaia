import fs from "fs";
import { type NextRequest, NextResponse } from "next/server";
import type { PageInfo } from "next-llms-txt";
import { createLLmsTxt } from "next-llms-txt";

import { getAllAlternatives } from "@/features/alternatives/data/alternativesData";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { FEATURES } from "@/features/landing/data/featuresData";
import { getAllPersonas } from "@/features/personas/data/personasData";
import { getAllBlogPosts } from "@/lib/blog";
import { siteConfig } from "@/lib/seo";

const BASE_URL = siteConfig.url;

/** Cap per dynamic section so the file stays a sane size for LLM ingestion. */
const MAX_ENTRIES_PER_SECTION = 200;

function extractMetadata(
  filePath: string,
): { title: string; description?: string } | null {
  try {
    const content = fs.readFileSync(filePath, "utf-8");
    const titleMatch = content.match(/\btitle:\s*["']([^"'\n]+)["']/);
    if (!titleMatch) return null;
    const descriptionMatch = content.match(
      /\bdescription:\s*["']([^"'\n]+)["']/,
    );
    return {
      title: titleMatch[1],
      description: descriptionMatch?.[1],
    };
  } catch {
    return null;
  }
}

function generateContent(
  _config: unknown,
  pages: PageInfo[] | undefined,
): string {
  const enriched: PageInfo[] = [];
  for (const page of pages ?? []) {
    if (page.route.includes("[")) continue;
    if (page.config?.title) {
      enriched.push(page);
      continue;
    }
    const meta = extractMetadata(page.filePath);
    if (!meta) continue;
    enriched.push({ ...page, config: { ...meta } });
  }
  enriched.sort((a, b) =>
    (a.config?.title ?? "").localeCompare(b.config?.title ?? ""),
  );

  const lines: string[] = [
    `# ${siteConfig.short_name}`,
    "",
    `> ${siteConfig.description}`,
    "",
    "## Pages",
  ];

  for (const page of enriched) {
    const desc = page.config?.description ? `: ${page.config.description}` : "";
    lines.push(`- [${page.config?.title}](${BASE_URL}${page.route})${desc}`);
  }

  return lines.join("\n");
}

const { GET: baseGET } = createLLmsTxt({
  baseUrl: BASE_URL,
  defaultConfig: {
    title: siteConfig.short_name,
    description: siteConfig.description,
  },
  autoDiscovery: {
    appDir: "src/app/[locale]/(landing)",
    rootDir: process.cwd(),
  },
  generator: generateContent,
});

interface DynamicEntry {
  title: string;
  url: string;
  description?: string;
}

/**
 * Programmatic SEO pages skipped by autoDiscovery (every "[slug]" route is
 * filtered out of `pages`), enumerated from the same data sources as the
 * sitemap so llms.txt never invents URLs. Canonical (default-locale) URLs
 * only. Synonym slugs with a canonicalSlug are excluded, mirroring the
 * sitemap's PageRank consolidation.
 */
async function buildDynamicSections(): Promise<string> {
  let comparisons: Awaited<ReturnType<typeof getAllComparisons>> = [];
  let alternatives: Awaited<ReturnType<typeof getAllAlternatives>> = [];
  let glossary: Awaited<ReturnType<typeof getAllGlossaryTerms>> = [];
  let combos: Awaited<ReturnType<typeof getAllCombos>> = [];
  let personas: Awaited<ReturnType<typeof getAllPersonas>> = [];
  let posts: Awaited<ReturnType<typeof getAllBlogPosts>> = [];
  try {
    [comparisons, alternatives, glossary, combos, personas, posts] =
      await Promise.all([
        getAllComparisons(),
        getAllAlternatives(),
        getAllGlossaryTerms(),
        getAllCombos(),
        getAllPersonas(),
        getAllBlogPosts(false),
      ]);
  } catch (error) {
    console.error("Error loading dynamic entries for llms.txt:", error);
    return "";
  }

  const sections: Array<{ heading: string; entries: DynamicEntry[] }> = [
    {
      heading: "Comparisons",
      entries: comparisons.slice(0, MAX_ENTRIES_PER_SECTION).map((c) => ({
        title: c.metaTitle,
        url: `${BASE_URL}/compare/${c.slug}`,
        description: c.metaDescription,
      })),
    },
    {
      heading: "Alternatives",
      entries: alternatives.slice(0, MAX_ENTRIES_PER_SECTION).map((a) => ({
        title: a.metaTitle,
        url: `${BASE_URL}/alternative-to/${a.slug}`,
        description: a.metaDescription,
      })),
    },
    {
      heading: "Glossary",
      entries: glossary
        .filter((t) => !t.canonicalSlug)
        .slice(0, MAX_ENTRIES_PER_SECTION)
        .map((t) => ({
          title: t.metaTitle,
          url: `${BASE_URL}/learn/${t.slug}`,
          description: t.metaDescription,
        })),
    },
    {
      heading: "Automations",
      entries: combos
        .filter((c) => !c.canonicalSlug)
        .slice(0, MAX_ENTRIES_PER_SECTION)
        .map((c) => ({
          title: c.metaTitle,
          url: `${BASE_URL}/automate/${c.slug}`,
          description: c.metaDescription,
        })),
    },
    {
      heading: "Personas",
      entries: personas.slice(0, MAX_ENTRIES_PER_SECTION).map((p) => ({
        title: p.metaTitle,
        url: `${BASE_URL}/for/${p.slug}`,
        description: p.metaDescription,
      })),
    },
    {
      heading: "Features",
      entries: FEATURES.slice(0, MAX_ENTRIES_PER_SECTION).map((f) => ({
        title: `${f.title} — GAIA`,
        url: `${BASE_URL}/features/${f.slug}`,
        description: f.subheadline,
      })),
    },
    {
      heading: "Blog",
      entries: posts.slice(0, MAX_ENTRIES_PER_SECTION).map((post) => ({
        title: post.title,
        url: `${BASE_URL}/blog/${post.slug}`,
        description: post.category,
      })),
    },
  ];

  const lines: string[] = [];
  for (const section of sections) {
    if (section.entries.length === 0) continue;
    lines.push("", `## ${section.heading}`);
    for (const entry of section.entries) {
      const desc = entry.description ? `: ${entry.description}` : "";
      lines.push(`- [${entry.title}](${entry.url})${desc}`);
    }
  }
  return lines.join("\n");
}

export async function GET(request: NextRequest) {
  const response = await baseGET(request);
  const { pathname } = new URL(request.url);
  // Only the index gets dynamic sections — *.html.md page payloads pass through untouched.
  if (pathname !== "/llms.txt" || !response.ok) {
    return response;
  }
  const body = await response.text();
  const extra = await buildDynamicSections();
  if (!extra) {
    return new NextResponse(body, {
      status: response.status,
      headers: response.headers,
    });
  }
  return new NextResponse(`${body}\n${extra}\n`, {
    status: response.status,
    headers: response.headers,
  });
}

export const revalidate = 3600;
