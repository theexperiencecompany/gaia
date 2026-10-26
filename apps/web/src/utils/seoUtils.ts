import type { Metadata } from "next";
import type { HowTo, HowToStep, Person, WithContext } from "schema-dts";
import { isSystemCreator } from "@/features/workflows/utils/creator";
import { type BlogContentPost, blogLastModified } from "@/lib/blog";
import {
  brandedTitle,
  generatePageMetadata,
  organizationRef,
  siteConfig,
} from "@/lib/seo";
import type { UseCase } from "@/types/features/workflowTypes";
import {
  generateUseCaseDescription,
  generateUseCaseTitle,
} from "@/utils/useCaseMeta";

/**
 * Extracts description from markdown content for meta descriptions
 */
function extractDescription(markdown: string, maxLength: number = 160): string {
  if (!markdown) return "";

  // Remove markdown syntax
  const text = markdown
    .replace(/#{1,6}\s+/g, "")
    .replace(/[*_]{1,2}([^*_]+)[*_]{1,2}/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/```[\s\S]*?```/g, "")
    .replace(/\s+/g, " ")
    .trim();

  if (text.length <= maxLength) return text;

  const truncated = text.substring(0, maxLength);
  const lastSpace = truncated.lastIndexOf(" ");
  return lastSpace > 100
    ? `${truncated.substring(0, lastSpace)}...`
    : `${truncated}...`;
}

/**
 * Generates metadata for a blog post
 */
export function generateBlogMetadata(blog: BlogContentPost): Metadata {
  return {
    ...generatePageMetadata({
      title: blog.metaTitle ?? blog.title,
      description: extractDescription(blog.content),
      path: `/blog/${blog.slug}`,
      image: blog.image || siteConfig.ogImage,
      type: "article",
      publishedTime: blog.date,
      modifiedTime: blogLastModified(blog),
      authors: blog.authors.map((author) => author.name),
      section: blog.category,
    }),
    authors: blog.authors.map((author) => ({ name: author.name })),
  };
}

/** Metadata for a use case page; a copy of another page passes that page's slug as canonical. */
export function generateUseCaseMetadata(
  useCase: UseCase,
  canonicalSlug: string = useCase.slug,
): Metadata {
  const description = generateUseCaseDescription(useCase);
  const canonicalUrl = `/use-cases/${canonicalSlug}`;
  const ogImageUrl = `/api/og/use-case?slug=${useCase.slug}`;

  const title = brandedTitle(generateUseCaseTitle(useCase));
  const keywords = [
    useCase.title,
    ...useCase.categories,
    ...useCase.integrations,
    "AI automation",
    "workflow automation",
    siteConfig.short_name,
  ].join(", ");

  return {
    // Absolute: brandedTitle has already decided whether " | GAIA" fits.
    title: { absolute: title },
    description,
    keywords,
    authors: useCase.creator
      ? [{ name: useCase.creator.name }]
      : [{ name: `${siteConfig.short_name} Team` }],

    openGraph: {
      title,
      description,
      url: canonicalUrl,
      siteName: siteConfig.name,
      images: [
        {
          url: ogImageUrl,
          width: 1200,
          height: 630,
          alt: `${useCase.title} - GAIA Workflow`,
        },
      ],
      type: "article",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [
        {
          url: ogImageUrl,
          width: 1200,
          height: 630,
          alt: `${useCase.title} - GAIA Workflow`,
        },
      ],
      site: "@trygaia",
      creator: "@trygaia",
    },
    alternates: { canonical: canonicalUrl },
    robots: { index: true, follow: true },
  };
}

/**
 * Generates JSON-LD structured data for a use case page
 */
export function generateUseCaseStructuredData(
  useCase: UseCase,
): WithContext<HowTo> {
  const ogImageUrl = `${siteConfig.url}/api/og/use-case?slug=${useCase.slug}`;

  const structuredData: WithContext<HowTo> = {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name: useCase.title,
    description: useCase.detailed_description || useCase.description,
    image: ogImageUrl,
    publisher: organizationRef,
    url: `${siteConfig.url}/use-cases/${useCase.slug}`,
    inLanguage: "en-US",
  };

  if (useCase.creator) {
    // GAIA's own workflows are authored by the organization, not a person called "GAIA Team".
    structuredData.author = isSystemCreator(useCase.creator)
      ? organizationRef
      : ({ "@type": "Person", name: useCase.creator.name } as Person);
  }

  if (useCase.steps && useCase.steps.length > 0) {
    structuredData.step = useCase.steps.map(
      (step, index): HowToStep => ({
        "@type": "HowToStep",
        position: index + 1,
        name: step.title || `Step ${index + 1}`,
        text: step.description,
      }),
    );
  }

  // Generate tools from steps
  if (useCase.steps && useCase.steps.length > 0) {
    const toolsFromSteps = useCase.steps.map((step) => ({
      "@type": "HowToTool" as const,
      name: step.category,
      description: step.description,
    }));

    if (toolsFromSteps.length > 0) {
      structuredData.tool = toolsFromSteps;
    }
  }

  return structuredData;
}
