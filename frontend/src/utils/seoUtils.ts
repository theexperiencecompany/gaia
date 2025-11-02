import { Metadata } from "next";
import type {
  Article,
  HowTo,
  HowToStep,
  ImageObject,
  Organization,
  Person,
  WithContext,
} from "schema-dts";

import { BlogPost } from "@/features/blog/api/blogApi";
import { UseCase } from "@/features/use-cases/constants/dummy-data";
import { siteConfig } from "@/lib/seo";

/**
 * Extracts description from markdown content for meta descriptions
 */
export function extractDescription(
  markdown: string,
  maxLength: number = 160,
): string {
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
    ? truncated.substring(0, lastSpace) + "..."
    : truncated + "...";
}

/**
 * Generates metadata for a blog post
 */
export function generateBlogMetadata(blog: BlogPost): Metadata {
  const description = extractDescription(blog.content);
  const canonicalUrl = `/blog/${blog.slug}`;
  const imageUrl = blog.image || "/og-image.webp";

  return {
    title: blog.title,
    description,
    authors:
      blog.author_details?.map((author) => ({ name: author.name })) ||
      blog.authors.map((name) => ({ name })),

    openGraph: {
      title: blog.title,
      description,
      url: canonicalUrl,
      siteName: siteConfig.name,
      images: [
        {
          url: imageUrl,
          width: 1200,
          height: 630,
          alt: blog.title,
          type: "image/webp",
        },
      ],
      type: "article",
      publishedTime: blog.date,
      authors:
        blog.author_details?.map((author) => author.name) || blog.authors,
      section: blog.category,
    },

    twitter: {
      card: "summary_large_image",
      title: blog.title,
      description,
      images: [
        {
          url: imageUrl,
          width: 1200,
          height: 630,
          alt: blog.title,
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
 * Generates JSON-LD structured data for a blog post
 */
export function generateBlogStructuredData(
  blog: BlogPost,
): WithContext<Article> {
  return {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: blog.title,
    description: extractDescription(blog.content),
    image: blog.image || "/og-image.webp",
    author:
      blog.author_details?.map(
        (author): Person => ({
          "@type": "Person",
          name: author.name,
          jobTitle: author.role,
        }),
      ) || blog.authors.map((name): Person => ({ "@type": "Person", name })),
    publisher: {
      "@type": "Organization",
      name: "GAIA",
      logo: {
        "@type": "ImageObject",
        url: "/images/logos/logo.webp",
      } as ImageObject,
    } as Organization,
    datePublished: blog.date,
    url: `/blog/${blog.slug}`,
    articleSection: blog.category,
    inLanguage: "en-US",
  };
}

/**
 * Generates metadata for a use case page
 */
export function generateUseCaseMetadata(useCase: UseCase): Metadata {
  const description = useCase.detailed_description || useCase.description || "";
  const canonicalUrl = `/use-cases/${useCase.slug}`;

  const title = `${useCase.title} - ${siteConfig.short_name} Use Case`;
  const keywords = [
    useCase.title,
    ...useCase.categories,
    ...useCase.integrations,
    "AI automation",
    "workflow automation",
    siteConfig.short_name,
  ].join(", ");

  return {
    title,
    description,
    keywords,
    authors: useCase.creator
      ? [{ name: useCase.creator.name }]
      : [{ name: `${siteConfig.short_name} Team` }],

    openGraph: {
      title,
      description,
      url: canonicalUrl,
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
  const structuredData: WithContext<HowTo> = {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name: useCase.title,
    description: useCase.detailed_description || useCase.description,
    image: "/og-image.webp",
    publisher: {
      "@type": "Organization",
      name: siteConfig.short_name,
      logo: {
        "@type": "ImageObject",
        url: "/images/logos/logo.webp",
      } as ImageObject,
    } as Organization,
    url: `/use-cases/${useCase.slug}`,
    inLanguage: "en-US",
  };

  if (useCase.creator) {
    structuredData.author = {
      "@type": "Person",
      name: useCase.creator.name,
    } as Person;
  }

  if (useCase.steps && useCase.steps.length > 0) {
    structuredData.step = useCase.steps.map(
      (step, index): HowToStep => ({
        "@type": "HowToStep",
        position: index + 1,
        name: step.title,
        text: step.description,
        ...(step.details && { description: step.details }),
      }),
    );
  }

  if (useCase.tools && useCase.tools.length > 0) {
    structuredData.tool = useCase.tools.map((tool) => ({
      "@type": "HowToTool",
      name: tool.name,
      description: tool.description,
    }));
  }

  return structuredData;
}
