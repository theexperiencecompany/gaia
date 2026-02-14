import type { MetadataRoute } from "next";

import { getAllComparisonSlugs } from "@/features/comparisons/data/comparisonsData";
import { getAllGlossaryTermSlugs } from "@/features/glossary/data/glossaryData";
import { workflowApi } from "@/features/workflows/api/workflowApi";
import { getAllBlogPosts } from "@/lib/blog";
import { fetchAllPaginated, isDevelopment } from "@/lib/fetchAll";
import { getSiteUrl } from "@/lib/seo";

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
  ];
}

type ChangeFreq = "daily" | "weekly" | "monthly" | "yearly";
const STATIC_PAGES: Array<{
  path: string;
  freq: ChangeFreq;
  priority: number;
}> = [
  { path: "", freq: "daily", priority: 1.0 },
  { path: "/pricing", freq: "weekly", priority: 0.9 },
  { path: "/marketplace", freq: "weekly", priority: 0.9 },
  { path: "/blog", freq: "daily", priority: 0.9 },
  { path: "/use-cases", freq: "weekly", priority: 0.9 },
  { path: "/download", freq: "weekly", priority: 0.9 },
  { path: "/compare", freq: "weekly", priority: 0.9 },
  { path: "/for", freq: "weekly", priority: 0.9 },
  { path: "/learn", freq: "weekly", priority: 0.8 },
  { path: "/faq", freq: "monthly", priority: 0.8 },
  { path: "/manifesto", freq: "monthly", priority: 0.8 },
  { path: "/about", freq: "monthly", priority: 0.8 },
  { path: "/docs", freq: "weekly", priority: 0.8 },
  { path: "/contact", freq: "monthly", priority: 0.7 },
  { path: "/brand", freq: "monthly", priority: 0.7 },
  { path: "/login", freq: "monthly", priority: 0.6 },
  { path: "/signup", freq: "monthly", priority: 0.6 },
  { path: "/status", freq: "daily", priority: 0.6 },
  { path: "/terms", freq: "monthly", priority: 0.5 },
  { path: "/privacy", freq: "monthly", priority: 0.5 },
  { path: "/request-feature", freq: "monthly", priority: 0.5 },
  { path: "/support", freq: "monthly", priority: 0.6 },
  { path: "/desktop", freq: "monthly", priority: 0.6 },
  { path: "/thanks", freq: "monthly", priority: 0.4 },
];

function getStaticPages(baseUrl: string): MetadataRoute.Sitemap {
  return STATIC_PAGES.map((p) => ({
    url: `${baseUrl}${p.path}`,
    changeFrequency: p.freq,
    priority: p.priority,
  }));
}

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
 */
async function getExploreWorkflowPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  try {
    const limit = isDevelopment() ? 50 : 1000;
    const exploreResp = await workflowApi.getExploreWorkflows(limit, 0);
    return exploreResp.workflows.map((wc) => ({
      url: `${baseUrl}/use-cases/${wc.id}`,
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
 */
async function getCommunityWorkflowPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  try {
    if (isDevelopment()) {
      const communityResponse = await workflowApi.getCommunityWorkflows(50, 0);
      return communityResponse.workflows.map((workflow) => ({
        url: `${baseUrl}/use-cases/${workflow.id}`,
        lastModified: new Date(workflow.created_at),
        changeFrequency: "weekly" as const,
        priority: 0.6,
      }));
    }

    const allWorkflows = await fetchAllPaginated(async (limit, offset) => {
      const resp = await workflowApi.getCommunityWorkflows(limit, offset);
      return {
        items: resp.workflows,
        total: resp.total || 0,
        hasMore: resp.workflows.length === limit,
      };
    }, 100);

    console.log(
      `[Sitemap] Generated ${allWorkflows.length} community workflow pages`,
    );

    return allWorkflows.map((workflow) => ({
      url: `${baseUrl}/use-cases/${workflow.id}`,
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
 * Marketplace integration pages
 */
async function getIntegrationPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  try {
    const apiUrl =
      process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    const apiBaseUrl = apiUrl.replace(/\/$/, "");

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

    console.log(
      `[Sitemap] Generated ${allIntegrations.length} integration pages`,
    );

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
    lastModified: new Date(),
    changeFrequency: "monthly" as const,
    priority: 0.8,
  }));
}

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
      lastModified: new Date(),
      changeFrequency: "monthly" as const,
      priority: 0.8,
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
    lastModified: new Date(),
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
      return getStaticPages(baseUrl);
    case SITEMAP_IDS.BLOG:
      return getBlogPages(baseUrl);
    case SITEMAP_IDS.EXPLORE:
      return getExploreWorkflowPages(baseUrl);
    case SITEMAP_IDS.COMMUNITY:
      return getCommunityWorkflowPages(baseUrl);
    case SITEMAP_IDS.INTEGRATIONS:
      return getIntegrationPages(baseUrl);
    case SITEMAP_IDS.COMPARISONS:
      return getComparisonPages(baseUrl);
    case SITEMAP_IDS.PERSONAS:
      return getPersonaPages(baseUrl);
    case SITEMAP_IDS.GLOSSARY:
      return getGlossaryPages(baseUrl);
    default:
      return [];
  }
}
