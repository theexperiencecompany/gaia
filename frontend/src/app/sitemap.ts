import type { MetadataRoute } from "next";

import { workflowApi } from "@/features/workflows/api/workflowApi";
import { getAllBlogPosts } from "@/lib/blog";

/**
 * Generate dynamic sitemap for GAIA
 * This includes all static pages, blog posts, use cases, and community workflows
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const baseUrl = "https://heygaia.io";

  // Static pages with their priorities and update frequencies
  const staticPages: MetadataRoute.Sitemap = [
    {
      url: baseUrl,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 1.0,
    },
    {
      url: `${baseUrl}/pricing`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.9,
    },
    {
      url: `${baseUrl}/manifesto`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${baseUrl}/about`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${baseUrl}/contact`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.7,
    },
    {
      url: `${baseUrl}/blog`,
      lastModified: new Date(),
      changeFrequency: "daily",
      priority: 0.9,
    },
    {
      url: `${baseUrl}/use-cases`,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 0.9,
    },
    {
      url: `${baseUrl}/login`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.6,
    },
    {
      url: `${baseUrl}/signup`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.6,
    },
    {
      url: `${baseUrl}/terms`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.5,
    },
    {
      url: `${baseUrl}/privacy`,
      lastModified: new Date(),
      changeFrequency: "monthly",
      priority: 0.5,
    },
  ];

  // Fetch blog posts dynamically from markdown files
  let blogPages: MetadataRoute.Sitemap = [];
  try {
    // Read blogs from markdown files instead of API
    const blogs = await getAllBlogPosts(false);
    // Commented out - Old API-based blog fetching
    // const blogs = await blogApi.getBlogs(false);
    blogPages = blogs.map((blog) => ({
      url: `${baseUrl}/blog/${blog.slug}`,
      lastModified: new Date(blog.date),
      changeFrequency: "monthly" as const,
      priority: 0.7,
    }));
  } catch (error) {
    console.error("Error fetching blogs for sitemap:", error);
  }

  // Fetch explore workflows from API to generate use-case pages.
  // If the API call fails, return no dynamic use-case pages.
  let useCasePages: MetadataRoute.Sitemap = [];
  try {
    const exploreResp = await workflowApi.getExploreWorkflows(200, 0);
    useCasePages = exploreResp.workflows.map((wc) => ({
      url: `${baseUrl}/use-cases/${wc.id}`,
      lastModified: new Date(wc.created_at),
      changeFrequency: "weekly" as const,
      priority: wc.categories?.includes("featured") ? 0.8 : 0.7,
    }));
  } catch (error) {
    console.error("Error fetching explore workflows for sitemap:", error);
    useCasePages = [];
  }

  // Fetch community workflows dynamically
  let communityWorkflowPages: MetadataRoute.Sitemap = [];
  try {
    const communityResponse = await workflowApi.getCommunityWorkflows(100, 0);
    communityWorkflowPages = communityResponse.workflows.map((workflow) => ({
      url: `${baseUrl}/use-cases/${workflow.id}`,
      lastModified: new Date(workflow.created_at),
      changeFrequency: "weekly" as const,
      priority: 0.6,
    }));
  } catch (error) {
    console.error("Error fetching community workflows for sitemap:", error);
  }

  return [
    ...staticPages,
    ...blogPages,
    ...useCasePages,
    ...communityWorkflowPages,
  ];
}
