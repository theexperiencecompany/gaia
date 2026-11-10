import type { MetadataRoute } from "next";

import { getAllAlternativeSlugs } from "@/features/alternatives/data/alternativesData";
import {
  comparisonCategoryGroups,
  comparisonCategoryPath,
} from "@/features/comparisons/data/comparisonCategories";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import {
  glossaryCategoryGroups,
  glossaryCategoryPath,
} from "@/features/glossary/data/glossaryCategories";
import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import { getAllCombos } from "@/features/integrations/data/combosData";
import {
  appPagePath,
  comboAppGroups,
} from "@/features/integrations/lib/comboApps";
import {
  MARKETPLACE_PATH,
  marketplaceDirectoryPages,
} from "@/features/integrations/lib/marketplaceDirectoryPages";
import {
  getAllCommunityIntegrations,
  getNativeIntegrations,
} from "@/features/integrations/lib/serverMarketplaceApi";
import { FEATURES } from "@/features/landing/data/featuresData";
import { getAllPersonaSlugs } from "@/features/personas/data/personasData";
import {
  getAllCommunityWorkflowsServer,
  getExploreWorkflowsServer,
} from "@/features/workflows/lib/serverWorkflowsApi";
import { findCopiedTemplate } from "@/features/workflows/lib/templateCopies";
import { defaultLocale, locales } from "@/i18n/config";
import { getAlternates } from "@/i18n/getAlternates";
import { blogLastModified, getAllBlogPosts } from "@/lib/blog";
import { hubPagePath, laterHubPageParams } from "@/lib/hubPagination";
import { getSiteUrl } from "@/lib/seo";

/**
 * Sitemap IDs for different content types.
 * Each ID generates a separate sitemap file, accessible at /sitemap/{id}.xml
 */
export const SITEMAP_IDS = {
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

export const ALL_SITEMAP_IDS = [
  SITEMAP_IDS.STATIC,
  SITEMAP_IDS.BLOG,
  SITEMAP_IDS.EXPLORE,
  SITEMAP_IDS.COMMUNITY,
  SITEMAP_IDS.INTEGRATIONS,
  SITEMAP_IDS.COMPARISONS,
  SITEMAP_IDS.PERSONAS,
  SITEMAP_IDS.GLOSSARY,
  SITEMAP_IDS.ALTERNATIVES,
  SITEMAP_IDS.INTEGRATION_COMBOS,
  SITEMAP_IDS.NATIVE_INTEGRATIONS,
] as const;

function withLocaleUrls(
  entries: MetadataRoute.Sitemap,
  baseUrl: string,
): MetadataRoute.Sitemap {
  return entries.flatMap((entry) => {
    const path = entry.url.startsWith(baseUrl)
      ? entry.url.slice(baseUrl.length)
      : entry.url;

    // Single source of truth with page <head> hreflang: the language map is
    // built by getAlternates (each entry's own alternates block renders from
    // the same helper), so sitemap and pages can never drift apart.
    const languages = getAlternates(path);

    return locales.map((locale) => ({
      ...entry,
      url: locale === defaultLocale ? entry.url : `${baseUrl}/${locale}${path}`,
      alternates: { languages },
    }));
  });
}

type ChangeFreq = "daily" | "weekly" | "monthly" | "yearly";
type StaticPage = { path: string; freq: ChangeFreq; priority: number };

const TRANSLATED_STATIC_PAGES: StaticPage[] = [
  { path: "/compare", freq: "weekly", priority: 0.9 },
  { path: "/alternative-to", freq: "weekly", priority: 0.9 },
  { path: "/automate", freq: "weekly", priority: 0.8 },
  { path: "/for", freq: "weekly", priority: 0.9 },
  { path: "/learn", freq: "weekly", priority: 0.8 },
];

const UNTRANSLATED_STATIC_PAGES: StaticPage[] = [
  { path: "", freq: "daily", priority: 1.0 },
  { path: "/pricing", freq: "weekly", priority: 0.9 },
  { path: "/marketplace", freq: "weekly", priority: 0.9 },
  { path: "/blog", freq: "daily", priority: 0.9 },
  { path: "/use-cases", freq: "weekly", priority: 0.9 },
  { path: "/download", freq: "weekly", priority: 0.9 },
  { path: "/faq", freq: "monthly", priority: 0.8 },
  { path: "/manifesto", freq: "monthly", priority: 0.8 },
  { path: "/about", freq: "monthly", priority: 0.8 },
  { path: "/features", freq: "weekly", priority: 0.8 },
  { path: "/bots", freq: "monthly", priority: 0.8 },
  { path: "/cli", freq: "monthly", priority: 0.7 },
  { path: "/contact", freq: "monthly", priority: 0.7 },
  { path: "/brand", freq: "monthly", priority: 0.7 },
  { path: "/terms", freq: "monthly", priority: 0.5 },
  { path: "/privacy", freq: "monthly", priority: 0.5 },
  { path: "/thanks", freq: "monthly", priority: 0.4 },
  { path: "/open-source-ai-assistant", freq: "monthly", priority: 0.9 },
  { path: "/best-ai-assistant", freq: "monthly", priority: 0.9 },
  { path: "/best-ai-email-assistant", freq: "monthly", priority: 0.9 },
  { path: "/best-ai-calendar-assistant", freq: "monthly", priority: 0.9 },
  { path: "/ai-chief-of-staff", freq: "monthly", priority: 0.9 },
  { path: "/inbox-zero-ai", freq: "monthly", priority: 0.9 },
  { path: "/best-ai-executive-assistant", freq: "monthly", priority: 0.9 },
  {
    path: "/ai-assistant-whatsapp-telegram-imessage",
    freq: "monthly",
    priority: 0.9,
  },
  { path: "/ai-assistant-with-memory", freq: "monthly", priority: 0.9 },
  { path: "/ai-assistant-like-jarvis", freq: "monthly", priority: 0.9 },
  {
    path: "/ai-assistant-that-can-see-your-screen",
    freq: "monthly",
    priority: 0.9,
  },
  {
    path: "/ai-assistant-that-uses-your-computer",
    freq: "monthly",
    priority: 0.9,
  },
  {
    path: "/how-to-use-ai-as-a-personal-assistant",
    freq: "monthly",
    priority: 0.8,
  },
];

/**
 * Blog post pages from markdown files
 */
async function getBlogPages(baseUrl: string): Promise<MetadataRoute.Sitemap> {
  const blogs = await getAllBlogPosts(false);
  return blogs.map((blog) => ({
    url: `${baseUrl}/blog/${blog.slug}`,
    lastModified: new Date(blogLastModified(blog)),
    changeFrequency: "weekly" as const,
    priority: 0.8,
  }));
}

/**
 * Explore workflows (GAIA team curated)
 */
async function getExploreWorkflowPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  const workflows = await getExploreWorkflowsServer(1000);
  return workflows.flatMap((wc) =>
    wc.slug
      ? [
          {
            url: `${baseUrl}/use-cases/${wc.slug}`,
            lastModified: new Date(wc.created_at),
            changeFrequency: "weekly" as const,
            priority: wc.categories?.includes("featured") ? 0.8 : 0.7,
          },
        ]
      : [],
  );
}

/**
 * Community workflows
 */
async function getCommunityWorkflowPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  const [workflows, templates] = await Promise.all([
    getAllCommunityWorkflowsServer(),
    getExploreWorkflowsServer(1000),
  ]);
  // A republished template canonicalizes to the template, so only the template is listed.
  return workflows.flatMap((workflow) =>
    workflow.slug && !findCopiedTemplate(workflow, templates)
      ? [
          {
            url: `${baseUrl}/use-cases/${workflow.slug}`,
            lastModified: new Date(workflow.created_at),
            changeFrequency: "weekly" as const,
            priority: 0.6,
          },
        ]
      : [],
  );
}

/**
 * Marketplace integration pages (community)
 */
async function getIntegrationPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  const [integrations, native] = await Promise.all([
    getAllCommunityIntegrations(),
    getNativeIntegrations(),
  ]);
  const directoryPages = laterHubPageParams(
    marketplaceDirectoryPages(native, integrations),
  ).map(({ page }) => ({
    url: `${baseUrl}${hubPagePath(MARKETPLACE_PATH, Number(page))}`,
    changeFrequency: "weekly" as const,
    priority: 0.6,
  }));
  return [
    ...integrations.map((integration) => ({
      url: `${baseUrl}/marketplace/${integration.slug}`,
      ...(integration.publishedAt
        ? { lastModified: new Date(integration.publishedAt) }
        : {}),
      changeFrequency: "weekly" as const,
      priority: 0.7,
    })),
    ...directoryPages,
  ];
}

/**
 * Comparison pages (GAIA vs competitors)
 */
async function getComparisonPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  const comparisons = await getAllComparisons();
  return [
    ...comparisons.map(({ slug }) => ({
      url: `${baseUrl}/compare/${slug}`,
      changeFrequency: "monthly" as const,
      priority: 0.8,
    })),
    ...comparisonCategoryGroups(comparisons).map((category) => ({
      url: `${baseUrl}${comparisonCategoryPath(category.slug)}`,
      changeFrequency: "weekly" as const,
      priority: 0.7,
    })),
  ];
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
 */
async function getPersonaPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  const slugs = await getAllPersonaSlugs();
  return slugs.map((slug) => ({
    url: `${baseUrl}/for/${slug}`,
    changeFrequency: "monthly" as const,
    priority: FEATURED_PERSONA_SLUGS.has(slug) ? 0.9 : 0.7,
  }));
}

/**
 * Glossary term pages (AI/productivity concepts)
 */
async function getGlossaryPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  const terms = await getAllGlossaryTerms();
  const pages: MetadataRoute.Sitemap = [];
  for (const term of terms) {
    pages.push({
      url: `${baseUrl}/learn/${term.slug}`,
      changeFrequency: "monthly",
      priority: 0.7,
    });
  }
  // Category labels do not decide which categories exist, so the message key stands in for them.
  for (const category of glossaryCategoryGroups(terms, (key) => key)) {
    pages.push({
      url: `${baseUrl}${glossaryCategoryPath(category.slug)}`,
      changeFrequency: "weekly",
      priority: 0.7,
    });
  }
  return pages;
}

/**
 * Alternative-to pages (GAIA as alternative to competitors)
 */
async function getAlternativePages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  const slugs = await getAllAlternativeSlugs();
  return slugs.map((slug) => ({
    url: `${baseUrl}/alternative-to/${slug}`,
    changeFrequency: "monthly" as const,
    priority: 0.8,
  }));
}

/**
 * Integration combo pages ([toolA] + [toolB] automation)
 */
async function getIntegrationComboPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  const allCombos = await getAllCombos();
  const pages: MetadataRoute.Sitemap = [];
  for (const combo of allCombos) {
    pages.push({
      url: `${baseUrl}/automate/${combo.slug}`,
      changeFrequency: "monthly",
      priority: 0.7,
    });
  }
  for (const app of comboAppGroups(allCombos)) {
    pages.push({
      url: `${baseUrl}${appPagePath(app.slug)}`,
      changeFrequency: "weekly",
      priority: 0.7,
    });
  }
  return pages;
}

/**
 * Native (platform) integration pages — first-party integrations served at
 * /marketplace/{slug}, distinct from the community integrations in shard 4.
 */
async function getNativeIntegrationPages(
  baseUrl: string,
): Promise<MetadataRoute.Sitemap> {
  const integrations = await getNativeIntegrations();
  return integrations.map((integration) => ({
    url: `${baseUrl}/marketplace/${integration.slug}`,
    changeFrequency: "weekly" as const,
    priority: 0.8,
  }));
}

export async function getSitemapEntries(
  id: number,
): Promise<MetadataRoute.Sitemap> {
  const baseUrl = getSiteUrl();

  switch (id) {
    case SITEMAP_IDS.STATIC:
      return [
        ...withLocaleUrls(
          TRANSLATED_STATIC_PAGES.map((p) => ({
            url: `${baseUrl}${p.path}`,
            changeFrequency: p.freq,
            priority: p.priority,
          })),
          baseUrl,
        ),
        ...UNTRANSLATED_STATIC_PAGES.map((p) => ({
          url: `${baseUrl}${p.path}`,
          changeFrequency: p.freq,
          priority: p.priority,
        })),
        ...FEATURES.map((feature) => ({
          url: `${baseUrl}/features/${feature.slug}`,
          changeFrequency: "monthly" as const,
          priority: 0.7,
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
      return withLocaleUrls(await getComparisonPages(baseUrl), baseUrl);
    case SITEMAP_IDS.PERSONAS:
      return withLocaleUrls(await getPersonaPages(baseUrl), baseUrl);
    case SITEMAP_IDS.GLOSSARY:
      return withLocaleUrls(await getGlossaryPages(baseUrl), baseUrl);
    case SITEMAP_IDS.ALTERNATIVES:
      return withLocaleUrls(await getAlternativePages(baseUrl), baseUrl);
    case SITEMAP_IDS.INTEGRATION_COMBOS:
      return withLocaleUrls(await getIntegrationComboPages(baseUrl), baseUrl);
    case SITEMAP_IDS.NATIVE_INTEGRATIONS:
      return getNativeIntegrationPages(baseUrl);
    default:
      return [];
  }
}
