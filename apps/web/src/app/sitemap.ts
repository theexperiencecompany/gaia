import type { MetadataRoute } from "next";

import { workflowApi } from "@/features/workflows/api/workflowApi";
import { getAllBlogPosts } from "@/lib/blog";

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
  ];
}

const BASE_URL = "https://heygaia.io";

/**
 * Static pages with their priorities and update frequencies
 */
function getStaticPages(): MetadataRoute.Sitemap {
  return [
    {
      url: BASE_URL,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 1.0,
    },
    {
      url: `${BASE_URL}/pricing`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.9,
    },
    {
      url: `${BASE_URL}/manifesto`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${BASE_URL}/about`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${BASE_URL}/contact`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.7,
    },
    {
      url: `${BASE_URL}/blog`,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 0.9,
    },
    {
      url: `${BASE_URL}/use-cases`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.9,
    },
    {
      url: `${BASE_URL}/login`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.6,
    },
    {
      url: `${BASE_URL}/signup`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.6,
    },
    {
      url: `${BASE_URL}/terms`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.5,
    },
    {
      url: `${BASE_URL}/privacy`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.5,
    },
    {
      url: `${BASE_URL}/brand`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.7,
    },
    {
      url: `${BASE_URL}/marketplace`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.9,
    },
  ];
}

/**
 * Blog post pages from markdown files
 */
async function getBlogPages(): Promise<MetadataRoute.Sitemap> {
  try {
    const blogs = await getAllBlogPosts(false);
    return blogs.map((blog) => ({
      url: `${BASE_URL}/blog/${blog.slug}`,
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
 * Explore workflows (GAIA team curated) - no limit on curated content
 */
async function getExploreWorkflowPages(): Promise<MetadataRoute.Sitemap> {
  try {
    const exploreResp = await workflowApi.getExploreWorkflows(500, 0);
    return exploreResp.workflows.map((wc) => ({
      url: `${BASE_URL}/use-cases/${wc.id}`,
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
 * Community workflows - increased limit for scalability
 */
async function getCommunityWorkflowPages(): Promise<MetadataRoute.Sitemap> {
  try {
    const communityResponse = await workflowApi.getCommunityWorkflows(1000, 0);
    return communityResponse.workflows.map((workflow) => ({
      url: `${BASE_URL}/use-cases/${workflow.id}`,
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
 * Marketplace integration pages - increased limit for scalability
 */
async function getIntegrationPages(): Promise<MetadataRoute.Sitemap> {
  try {
    const apiUrl =
      process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    const apiBaseUrl = apiUrl.replace(/\/$/, "");
    const response = await fetch(
      `${apiBaseUrl}/integrations/community?limit=500`,
      {
        next: { revalidate: 3600 },
      },
    );
    if (response.ok) {
      const data = await response.json();
      return (data.integrations || []).map(
        (integration: {
          integrationId: string;
          publishedAt?: string;
          createdAt?: string;
        }) => ({
          url: `${BASE_URL}/marketplace/${integration.integrationId}`,
          lastModified: new Date(
            integration.publishedAt || integration.createdAt || Date.now(),
          ),
          changeFrequency: "weekly" as const,
          priority: 0.7,
        }),
      );
    }
    return [];
  } catch (error) {
    console.error("Error fetching integrations for sitemap:", error);
    return [];
  }
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

  switch (id) {
    case SITEMAP_IDS.STATIC:
      return getStaticPages();
    case SITEMAP_IDS.BLOG:
      return getBlogPages();
    case SITEMAP_IDS.EXPLORE:
      return getExploreWorkflowPages();
    case SITEMAP_IDS.COMMUNITY:
      return getCommunityWorkflowPages();
    case SITEMAP_IDS.INTEGRATIONS:
      return getIntegrationPages();
    default:
      return [];
  }
}
