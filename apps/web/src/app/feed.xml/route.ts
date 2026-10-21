import { getAllAlternatives } from "@/features/alternatives/data/alternativesData";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { getAllCommunityIntegrations } from "@/features/integrations/lib/serverMarketplaceApi";
import { FEATURES } from "@/features/landing/data/featuresData";
import { getAllPersonas } from "@/features/personas/data/personasData";
import {
  getAllCommunityWorkflowsServer,
  getExploreWorkflowsServer,
} from "@/features/workflows/lib/serverWorkflowsApi";
import { getAllBlogPosts } from "@/lib/blog";
import { MARKETING_PAGES } from "@/lib/marketingPages";
import { siteConfig } from "@/lib/seo";

interface FeedItem {
  title: string;
  link: string;
  description: string;
  pubDate: string;
  category: string;
}

function escapeXml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function buildItem(item: FeedItem): string {
  return `
    <item>
      <title><![CDATA[${item.title}]]></title>
      <link>${item.link}</link>
      <guid isPermaLink="true">${item.link}</guid>
      <description><![CDATA[${item.description}]]></description>
      <pubDate>${item.pubDate}</pubDate>
      <category>${escapeXml(item.category)}</category>
    </item>`;
}

function getStaticPages(baseUrl: string, buildDate: string): FeedItem[] {
  return MARKETING_PAGES.map((page) => ({
    title: page.title,
    link: `${baseUrl}${page.path}`,
    description: page.description,
    pubDate: buildDate,
    category: page.category,
  }));
}

function getFeaturePages(baseUrl: string, buildDate: string): FeedItem[] {
  return FEATURES.map((feature) => ({
    title: `${feature.title} - ${feature.tagline}`,
    link: `${baseUrl}/features/${feature.slug}`,
    description: feature.subheadline,
    pubDate: buildDate,
    category: `Features / ${feature.category}`,
  }));
}

async function getComparisonPages(
  baseUrl: string,
  buildDate: string,
): Promise<FeedItem[]> {
  const all = await getAllComparisons();
  return all.map((item) => ({
    title: item.metaTitle || `GAIA vs ${item.name}`,
    link: `${baseUrl}/compare/${item.slug}`,
    description: item.metaDescription || item.description,
    pubDate: buildDate,
    category: "Comparisons",
  }));
}

async function getAlternativePages(
  baseUrl: string,
  buildDate: string,
): Promise<FeedItem[]> {
  const all = await getAllAlternatives();
  return all.map((item) => ({
    title: item.metaTitle || `GAIA Alternative to ${item.name}`,
    link: `${baseUrl}/alternative-to/${item.slug}`,
    description: item.metaDescription || item.tagline,
    pubDate: buildDate,
    category: "Alternatives",
  }));
}

async function getPersonaPages(
  baseUrl: string,
  buildDate: string,
): Promise<FeedItem[]> {
  const all = await getAllPersonas();
  return all.map((item) => ({
    title: item.metaTitle || `GAIA for ${item.title}`,
    link: `${baseUrl}/for/${item.slug}`,
    description: item.metaDescription || item.intro,
    pubDate: buildDate,
    category: "Built For",
  }));
}

async function getGlossaryPages(
  baseUrl: string,
  buildDate: string,
): Promise<FeedItem[]> {
  const all = await getAllGlossaryTerms();
  const items: FeedItem[] = [];
  // Victims excluded via _slugs.json (see sitemapData.ts) — no filter here.
  for (const term of all) {
    items.push({
      title: term.metaTitle || term.term,
      link: `${baseUrl}/learn/${term.slug}`,
      description: term.metaDescription || term.definition,
      pubDate: buildDate,
      category: "Glossary",
    });
  }
  return items;
}

async function getComboPages(
  baseUrl: string,
  buildDate: string,
): Promise<FeedItem[]> {
  const all = await getAllCombos();
  const items: FeedItem[] = [];
  for (const combo of all) {
    items.push({
      title: combo.metaTitle || `${combo.toolA} + ${combo.toolB} Automation`,
      link: `${baseUrl}/automate/${combo.slug}`,
      description: combo.metaDescription || combo.tagline,
      pubDate: buildDate,
      category: "Automation Combos",
    });
  }
  return items;
}

async function getIntegrationItems(baseUrl: string): Promise<FeedItem[]> {
  const integrations = await getAllCommunityIntegrations();
  return integrations.map((integration) => ({
    title: `${integration.name} Integration`,
    link: `${baseUrl}/marketplace/${integration.slug}`,
    description: integration.description,
    pubDate: new Date(integration.publishedAt ?? Date.now()).toUTCString(),
    category: "Integrations",
  }));
}

/** Blog posts from the local content, the same source the sitemap and /blog render. */
async function getBlogItems(baseUrl: string): Promise<FeedItem[]> {
  const posts = await getAllBlogPosts(true);
  return posts.map((post) => ({
    title: post.title,
    link: `${baseUrl}/blog/${post.slug}`,
    description: post.content
      .replace(/[#*`[\]()]/g, "")
      .replace(/\n/g, " ")
      .slice(0, 500)
      .trim(),
    pubDate: new Date(post.date).toUTCString(),
    category: post.category || "Blog",
  }));
}

async function getWorkflowItems(baseUrl: string): Promise<FeedItem[]> {
  const [explore, community] = await Promise.all([
    getExploreWorkflowsServer(1000),
    getAllCommunityWorkflowsServer(),
  ]);
  const seen = new Set<string>();
  const items: FeedItem[] = [];
  for (const wf of [...explore, ...community]) {
    if (!wf.slug || seen.has(wf.slug)) continue;
    seen.add(wf.slug);
    items.push({
      title: wf.title,
      link: `${baseUrl}/use-cases/${wf.slug}`,
      description:
        wf.description ||
        `AI workflow: ${wf.title}. Automate this use case with GAIA.`,
      pubDate: new Date(wf.created_at).toUTCString(),
      category: wf.categories?.includes("featured")
        ? "Featured Workflows"
        : "Community Workflows",
    });
  }
  return items;
}

export async function GET() {
  try {
    const baseUrl = siteConfig.url;
    // Evaluated per request (not at module load) so a long-lived server process
    // never serves stale build dates.
    const buildDate = new Date().toUTCString();

    const [
      blogItems,
      workflowItems,
      integrationItems,
      comparisonPages,
      alternativePages,
      glossaryPages,
      comboPages,
      personaPages,
    ] = await Promise.all([
      getBlogItems(baseUrl),
      getWorkflowItems(baseUrl),
      getIntegrationItems(baseUrl),
      getComparisonPages(baseUrl, buildDate),
      getAlternativePages(baseUrl, buildDate),
      getGlossaryPages(baseUrl, buildDate),
      getComboPages(baseUrl, buildDate),
      getPersonaPages(baseUrl, buildDate),
    ]);

    const allItems: FeedItem[] = [
      ...getStaticPages(baseUrl, buildDate),
      ...getFeaturePages(baseUrl, buildDate),
      ...comparisonPages,
      ...alternativePages,
      ...personaPages,
      ...glossaryPages,
      ...comboPages,
      ...integrationItems,
      ...blogItems,
      ...workflowItems,
    ];

    const rssItems = allItems.map(buildItem).join("");

    const rss = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>GAIA - Your Personal AI Assistant</title>
    <link>${baseUrl}</link>
    <description>${escapeXml(siteConfig.description)}</description>
    <language>en-us</language>
    <lastBuildDate>${new Date().toUTCString()}</lastBuildDate>
    <atom:link href="${baseUrl}/feed.xml" rel="self" type="application/rss+xml"/>
    <image>
      <url>${baseUrl}/images/logos/logo.webp</url>
      <title>GAIA</title>
      <link>${baseUrl}</link>
    </image>
    ${rssItems}
  </channel>
</rss>`;

    return new Response(rss, {
      headers: {
        "Content-Type": "application/xml; charset=utf-8",
        "Cache-Control": "public, max-age=3600, s-maxage=3600",
      },
    });
  } catch (error) {
    console.error("Error generating full-site RSS feed:", error);
    return new Response("Error generating RSS feed", { status: 500 });
  }
}
