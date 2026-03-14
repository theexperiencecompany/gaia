import type { MetadataRoute } from "next";

import { getAllAlternativeSlugs } from "@/features/alternatives/data/alternativesData";
import { getAllComparisonSlugs } from "@/features/comparisons/data/comparisonsData";
import { getAllGlossaryTermSlugs } from "@/features/glossary/data/glossaryData";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { workflowApi } from "@/features/workflows/api/workflowApi";
import { defaultLocale, locales } from "@/i18n/config";
import { getAllBlogPosts } from "@/lib/blog";
import { fetchAllPaginated, isDevelopment } from "@/lib/fetchAll";
import { getSiteUrl } from "@/lib/seo";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

/**
 * Sitemap IDs for different content types.
 * Each ID generates a separate sitemap file, accessible at /sitemap/{id}.xml
 */
const SITEMAP_IDS = {
  STATIC: 0,
  BLOG: 1,
  EXPLORE: 2,
  COMMUNITY: 3,
  INTEGRATIONS: 4,
  COMPARISONS: 5,
  PERSONAS: 6,
  GLOSSARY: 7,
  ALTERNATIVES: 8,
  INTEGRATION_COMBOS: 9,
  NATIVE_INTEGRATIONS: 10,
} as const;

/**
 * Generate sitemap IDs for Next.js sitemap index.
 * This creates multiple sitemaps: /sitemap/0.xml, /sitemap/1.xml, etc.
 * The main /sitemap.xml serves as an index pointing to all child sitemaps.
 */
export async function generateSitemaps() {
  return [
    { id: SITEMAP_IDS.STATIC },
    { id: SITEMAP_IDS.BLOG },
    { id: SITEMAP_IDS.EXPLORE },
    { id: SITEMAP_IDS.COMMUNITY },
    { id: SITEMAP_IDS.INTEGRATIONS },
    { id: SITEMAP_IDS.COMPARISONS },
    { id: SITEMAP_IDS.PERSONAS },
    { id: SITEMAP_IDS.GLOSSARY },
    { id: SITEMAP_IDS.ALTERNATIVES },
    { id: SITEMAP_IDS.INTEGRATION_COMBOS },
    { id: SITEMAP_IDS.NATIVE_INTEGRATIONS },
  ];
}

function withLocaleUrls(
  entries: MetadataRoute.Sitemap,
  baseUrl: string,
): MetadataRoute.Sitemap {
  return entries.flatMap((entry) => {
    const path = entry.url.startsWith(baseUrl)
      ? entry.url.slice(baseUrl.length)
      : entry.url;

    const languages: Record<string, string> = {};
    for (const locale of locales) {
      languages[locale] =
        locale === defaultLocale
          ? `${baseUrl}${path}`
          : `${baseUrl}/${locale}${path}`;
    }
    languages["x-default"] = `${baseUrl}${path}`;

    return locales.map((locale) => ({
      ...entry,
      url: locale === defaultLocale ? entry.url : `${baseUrl}/${locale}${path}`,
      alternates: { languages },
    }));
  });
}

const BUILD_DATE = new Date().toISOString();

type ChangeFreq = "daily" | "weekly" | "monthly" | "yearly";
type StaticPage = { path: string; freq: ChangeFreq; priority: number };

const TRANSLATED_STATIC_PAGES: Array<StaticPage> = [
  { path: "/compare", freq: "weekly", priority: 0.5 },
  { path: "/alternative-to", freq: "weekly", priority: 0.5 },
  { path: "/automate", freq: "weekly", priority: 0.5 },
  { path: "/for", freq: "weekly", priority: 0.5 },
  { path: "/learn", freq: "weekly", priority: 0.5 },
];

const UNTRANSLATED_STATIC_PAGES: Array<StaticPage> = [
  { path: "", freq: "daily", priority: 1.0 },
  { path: "/pricing", freq: "weekly", priority: 0.9 },
  { path: "/marketplace", freq: "weekly", priority: 0.9 },
  { path: "/blog", freq: "daily", priority: 0.9 },
  { path: "/use-cases", freq: "weekly", priority: 0.9 },
  { path: "/download", freq: "weekly", priority: 0.9 },
  { path: "/faq", freq: "monthly", priority: 0.8 },
  { path: "/manifesto", freq: "monthly", priority: 0.8 },
  { path: "/about", freq: "monthly", priority: 0.8 },
  { path: "/contact", freq: "monthly", priority: 0.7 },
  { path: "/brand", freq: "monthly", priority: 0.7 },
  { path: "/login", freq: "monthly", priority: 0.6 },
  { path: "/signup", freq: "monthly", priority: 0.6 },
  { path: "/terms", freq: "monthly", priority: 0.5 },
  { path: "/privacy", freq: "monthly", priority: 0.5 },
  { path: "/thanks", freq: "monthly", priority: 0.4 },
  { path: "/open-source-ai-assistant", freq: "monthly", priority: 0.9 },
  { path: "/ai-chief-of-staff", freq: "monthly", priority: 0.9 },
  { path: "/inbox-zero-ai", freq: "monthly", priority: 0.9 },
];

/**
 * Blog post pages from markdown files
 */
async function getBlogPages(baseUrl: string): Promise<MetadataRoute.Sitemap> {
  try {
    const blogs = await getAllBlogPosts(false);
    return blogs.map((blog) => ({
      url: `${baseUrl}/blog/${blog.slug}`,
      lastModified: new Date(blog.date),
      changeFrequency: "monthly" as const,
      priority: 0.7,
    }));
  } catch (error) {
    console.error("Error fetching blogs for sitemap:", error);
    return [];
  }
}

/**
 * Explore workflows (GAIA team curated)
 * Uses raw fetch with server API URL instead of authenticated axios client,
 * since sitemap generation runs at build time without auth credentials.
 */
async function getExploreWorkflowPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  try {
    const limit = isDevelopment() ? 50 : 1000;
    const exploreResp = await workflowApi.getExploreWorkflows(limit, 0);
    return exploreResp.workflows.map((wc) => ({
      url: `${baseUrl}/use-cases/${wc.slug ?? wc.id}`,
      lastModified: new Date(wc.created_at),
      changeFrequency: "weekly" as const,
      priority: wc.categories?.includes("featured") ? 0.8 : 0.7,
    }));
  } catch (error) {
    console.error("Error fetching explore workflows for sitemap:", error);
    return [];
  }
}

/**
 * Community workflows
 * Uses raw fetch with server API URL instead of authenticated axios client,
 * since sitemap generation runs at build time without auth credentials.
 */
async function getCommunityWorkflowPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  try {
    if (isDevelopment()) {
      const communityResponse = await workflowApi.getCommunityWorkflows(50, 0);
      return communityResponse.workflows.map((workflow) => ({
        url: `${baseUrl}/use-cases/${workflow.slug ?? workflow.id}`,
        lastModified: new Date(workflow.created_at),
        changeFrequency: "weekly" as const,
        priority: 0.6,
      }));
    }

    const apiBaseUrl = getServerApiBaseUrl();
    if (!apiBaseUrl) {
      console.warn(
        "[Sitemap] No API base URL configured, skipping community workflows",
      );
      return [];
    }

    type CommunityWorkflow = { id: string; slug?: string; created_at: string };

    const allWorkflows = await fetchAllPaginated<CommunityWorkflow>(
      async (limit, offset) => {
        const response = await fetch(
          `${apiBaseUrl}/workflows/community?limit=${limit}&offset=${offset}`,
          { next: { revalidate: 3600 } },
        );
        if (!response.ok) return { items: [], total: 0, hasMore: false };

        const data = await response.json();
        return {
          items: data.workflows || [],
          total: data.total || 0,
          hasMore: (data.workflows || []).length === limit,
        };
      },
      100,
    );

    return allWorkflows.map((workflow) => ({
      url: `${baseUrl}/use-cases/${workflow.slug ?? workflow.id}`,
      lastModified: new Date(workflow.created_at),
      changeFrequency: "weekly" as const,
      priority: 0.6,
    }));
  } catch (error) {
    console.error("Error fetching community workflows for sitemap:", error);
    return [];
  }
}

/**
 * Native/platform integration pages (Google Calendar, GitHub, Slack, etc.)
 * Uses the public /integrations/config endpoint — no auth required.
 */
async function getNativeIntegrationPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  try {
    const apiBaseUrl = getServerApiBaseUrl();
    if (!apiBaseUrl) return [];

    const response = await fetch(`${apiBaseUrl}/integrations/config`, {
      next: { revalidate: 3600 },
    });
    if (!response.ok) {
      console.error(
        `[Sitemap] Native integrations config returned ${response.status}`,
      );
      return [];
    }

    const data = await response.json();
    type NativeIntegration = { id: string; available: boolean };

    return ((data.integrations as NativeIntegration[]) || [])
      .filter((i) => i.available === true)
      .map((i) => ({
        url: `${baseUrl}/marketplace/${i.id}`,
        lastModified: BUILD_DATE,
        changeFrequency: "monthly" as const,
        priority: 0.7,
      }));
  } catch (error) {
    console.error("Error fetching native integrations for sitemap:", error);
    return [];
  }
}

/**
 * Marketplace integration pages
 */
async function getIntegrationPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  try {
    const apiBaseUrl = getServerApiBaseUrl();
    if (!apiBaseUrl) return [];

    if (isDevelopment()) {
      const response = await fetch(
        `${apiBaseUrl}/integrations/community?limit=50`,
        { next: { revalidate: 3600 } },
      );
      if (response.ok) {
        const data = await response.json();
        return (data.integrations || []).map(
          (integration: {
            slug: string;
            publishedAt?: string;
            createdAt?: string;
          }) => ({
            url: `${baseUrl}/marketplace/${integration.slug}`,
            lastModified: new Date(
              integration.publishedAt || integration.createdAt || Date.now(),
            ),
            changeFrequency: "weekly" as const,
            priority: 0.7,
          }),
        );
      }
      return [];
    }

    const allIntegrations: Array<{
      slug: string;
      publishedAt?: string;
      createdAt?: string;
    }> = await fetchAllPaginated(async (limit, offset) => {
      const response = await fetch(
        `${apiBaseUrl}/integrations/community?limit=${limit}&offset=${offset}`,
        { next: { revalidate: 3600 } },
      );
      if (!response.ok) return { items: [], total: 0, hasMore: false };

      const data = await response.json();
      return {
        items: data.integrations || [],
        total: data.total || 0,
        hasMore: data.hasMore !== false,
      };
    }, 100);

    return allIntegrations.map(
      (integration: {
        slug: string;
        publishedAt?: string;
        createdAt?: string;
      }) => ({
        url: `${baseUrl}/marketplace/${integration.slug}`,
        lastModified: new Date(
          integration.publishedAt || integration.createdAt || Date.now(),
        ),
        changeFrequency: "weekly" as const,
        priority: 0.7,
      }),
    );
  } catch (error) {
    console.error("Error fetching integrations for sitemap:", error);
    return [];
  }
}

/**
 * Comparison pages (GAIA vs competitors)
 */
function getComparisonPages(baseUrl: string): MetadataRoute.Sitemap {
  const slugs = getAllComparisonSlugs();
  return slugs.map((slug) => ({
    url: `${baseUrl}/compare/${slug}`,
    lastModified: BUILD_DATE,
    changeFrequency: "monthly" as const,
    priority: 0.8,
  }));
}

const FEATURED_PERSONA_SLUGS = new Set([
  "startup-founders",
  "software-developers",
  "sales-professionals",
  "product-managers",
  "engineering-managers",
  "agency-owners",
  "financial-advisors",
  "healthcare-professionals",
  "data-analysts",
  "hr-managers",
]);

/**
 * Persona pages (AI assistant for [role])
 * Dynamically imports to avoid circular dependency issues at build time.
 */
async function getPersonaPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  try {
    const { getAllPersonaSlugs } = await import(
      "@/features/personas/data/personasData"
    );
    const slugs = getAllPersonaSlugs();
    return slugs.map((slug) => ({
      url: `${baseUrl}/for/${slug}`,
      lastModified: BUILD_DATE,
      changeFrequency: "monthly" as const,
      priority: FEATURED_PERSONA_SLUGS.has(slug) ? 0.9 : 0.7,
    }));
  } catch (error) {
    console.error("Error generating persona sitemap pages:", error);
    return [];
  }
}

/**
 * Glossary term pages (AI/productivity concepts)
 */
function getGlossaryPages(baseUrl: string): MetadataRoute.Sitemap {
  const slugs = getAllGlossaryTermSlugs();
  return slugs.map((slug) => ({
    url: `${baseUrl}/learn/${slug}`,
    lastModified: BUILD_DATE,
    changeFrequency: "monthly" as const,
    priority: 0.7,
  }));
}

/**
 * Alternative-to pages (GAIA as alternative to competitors)
 */
function getAlternativePages(baseUrl: string): MetadataRoute.Sitemap {
  const slugs = getAllAlternativeSlugs();
  return slugs.map((slug) => ({
    url: `${baseUrl}/alternative-to/${slug}`,
    lastModified: BUILD_DATE,
    changeFrequency: "monthly" as const,
    priority: 0.8,
  }));
}

/**
 * Integration combo pages ([toolA] + [toolB] automation)
 */
function getIntegrationComboPages(baseUrl: string): MetadataRoute.Sitemap {
  const allCombos = getAllCombos();
  return allCombos
    .filter((c) => !c.canonicalSlug)
    .map((combo) => ({
      url: `${baseUrl}/automate/${combo.slug}`,
      lastModified: BUILD_DATE,
      changeFrequency: "monthly" as const,
      priority: 0.7,
    }));
}

/**
 * Generate dynamic sitemap for GAIA.
 * Uses sitemap index pattern with separate sitemaps for each content type.
 * Note: In Next.js 16.0.0+, the id is passed as a Promise that resolves to a string.
 */
export default async function sitemap(props: {
  id: Promise<string>;
}): Promise<MetadataRoute.Sitemap> {
  const idString = await props.id;
  const id = Number(idString);
  const baseUrl = getSiteUrl();

  switch (id) {
    case SITEMAP_IDS.STATIC:
      return [
        ...withLocaleUrls(
          TRANSLATED_STATIC_PAGES.map((p) => ({
            url: `${baseUrl}${p.path}`,
            lastModified: BUILD_DATE,
            changeFrequency: p.freq,
            priority: p.priority,
          })),
          baseUrl,
        ),
        ...UNTRANSLATED_STATIC_PAGES.map((p) => ({
          url: `${baseUrl}${p.path}`,
          lastModified: BUILD_DATE,
          changeFrequency: p.freq,
          priority: p.priority,
        })),
      ];
    case SITEMAP_IDS.BLOG:
      return getBlogPages(baseUrl);
    case SITEMAP_IDS.EXPLORE:
      return getExploreWorkflowPages(baseUrl);
    case SITEMAP_IDS.COMMUNITY:
      return getCommunityWorkflowPages(baseUrl);
    case SITEMAP_IDS.INTEGRATIONS:
      return getIntegrationPages(baseUrl);
    case SITEMAP_IDS.COMPARISONS:
      return withLocaleUrls(getComparisonPages(baseUrl), baseUrl);
    case SITEMAP_IDS.PERSONAS:
      return withLocaleUrls(await getPersonaPages(baseUrl), baseUrl);
    case SITEMAP_IDS.GLOSSARY:
      return withLocaleUrls(getGlossaryPages(baseUrl), baseUrl);
    case SITEMAP_IDS.ALTERNATIVES:
      return withLocaleUrls(getAlternativePages(baseUrl), baseUrl);
    case SITEMAP_IDS.INTEGRATION_COMBOS:
      return withLocaleUrls(getIntegrationComboPages(baseUrl), baseUrl);
    case SITEMAP_IDS.NATIVE_INTEGRATIONS:
      return getNativeIntegrationPages(baseUrl);
    default:
      return [];
  }
}
