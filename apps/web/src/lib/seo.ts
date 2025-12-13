import type { Metadata } from "next";
import type {
  AboutPage,
  Answer,
  Article,
  BreadcrumbList,
  ContactPage,
  ContactPoint,
  FAQPage,
  HowTo,
  HowToStep,
  ImageObject,
  ItemList,
  ListItem,
  Offer,
  Organization,
  Person,
  Question,
  SoftwareApplication,
  WebPage,
  WebSite,
  WithContext,
} from "schema-dts";

// Site-wide SEO Configuration
export const siteConfig = {
  short_name: "GAIA",
  name: "GAIA - Your Personal AI Assistant",
  fullName: "GAIA - Your Personal AI Assistant from The Experience Company",
  description:
    "GAIA is your open-source personal AI assistant to proactively manage your email, calendar, todos, workflows and all your digital tools to boost productivity.",
  url: "https://heygaia.io",
  ogImage: "/og-image.webp",
  links: {
    twitter: "https://x.com/trygaia",
    github: "https://github.com/theexperiencecompany",
    discord: "https://discord.heygaia.io",
    linkedin: "https://www.linkedin.com/company/heygaia",
    youtube: "https://youtube.com/@heygaia_io",
    whatsapp: "https://whatsapp.heygaia.io",
  },
  founders: [
    {
      name: "Aryan Randeriya",
      role: "Founder & CEO",
      twitter: "https://twitter.com/aryanranderiya",
      linkedin: "https://www.linkedin.com/in/aryanranderiya/",
    },
    {
      name: "Dhruv Maradiya",
      role: "Founder & CTO",
      twitter: "https://twitter.com/dhruvmaradiya",
      linkedin: "https://www.linkedin.com/in/dhruvmaradiya/",
    },
  ],
} as const;

// Common keywords for all pages
export const commonKeywords = [
  "GAIA",
  "GAIA AI",
  "heygaia",
  "AI Assistant",
  "Personal AI",
  "Productivity",
  "Automation",
  "Task Management",
  "Virtual Assistant",
  "Smart Assistant",
  "AI Productivity Tool",
  "Digital Assistant",
];

/**
 * Generate canonical URL for a page
 */
export function getCanonicalUrl(path: string): string {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  // Return relative URL - metadataBase in layout will handle absolute URL
  return cleanPath;
}

/**
 * Generate comprehensive page metadata with SEO best practices
 */
export interface PageMetadataOptions {
  title: string;
  description?: string;
  path: string;
  keywords?: string[];
  image?: string;
  type?: "website" | "article" | "profile";
  publishedTime?: string;
  modifiedTime?: string;
  authors?: string[];
  noIndex?: boolean;
  section?: string;
}

export function generatePageMetadata({
  title,
  description = siteConfig.description,
  path,
  keywords = [],
  image = siteConfig.ogImage,
  type = "website",
  publishedTime,
  modifiedTime,
  authors,
  noIndex = false,
  section,
}: PageMetadataOptions): Metadata {
  const url = getCanonicalUrl(path);

  // For homepage, use absolute title to prevent template from adding suffix
  // For other pages, use simple title string to let template add "| GAIA"
  const isHomepage = path === "/" || title === siteConfig.name;
  const pageTitle = isHomepage ? { absolute: siteConfig.name } : title;

  // Full title for OpenGraph (always includes suffix for non-homepage)
  const fullTitle = isHomepage
    ? siteConfig.fullName
    : `${title} | ${siteConfig.short_name}`;

  const allKeywords = [...commonKeywords, ...keywords];

  // Image URL: Return relative path or absolute URL
  // Next.js metadataBase will resolve relative URLs automatically
  const imageUrl = image.startsWith("http")
    ? image
    : image.startsWith("/")
      ? image
      : `/${image}`;

  const metadata: Metadata = {
    title: pageTitle,
    description,
    keywords: allKeywords,
    alternates: {
      canonical: url,
    },
    openGraph: {
      title: fullTitle,
      description,
      url,
      siteName: siteConfig.fullName,
      images: [
        {
          url: imageUrl,
          width: 1200,
          height: 630,
          alt: `${title} - ${siteConfig.short_name}`,
          type: "image/webp",
        },
      ],
      locale: "en_US",
      type,
    },
    twitter: {
      card: "summary_large_image",
      title: fullTitle,
      description,
      images: [
        {
          url: imageUrl,
          width: 1200,
          height: 630,
          alt: `${title} - ${siteConfig.short_name}`,
        },
      ],
      creator: "@trygaia",
      site: "@trygaia",
    },
  };

  // Add article-specific metadata
  if (type === "article") {
    metadata.openGraph = {
      ...metadata.openGraph,
      type: "article",
      publishedTime,
      modifiedTime,
      authors,
      section,
    };
  }

  // Add noindex for private pages
  if (noIndex) {
    metadata.robots = {
      index: false,
      follow: false,
    };
  }

  return metadata;
}

/**
 * Generate Organization structured data (JSON-LD)
 */
export function generateOrganizationSchema(): WithContext<Organization> {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: siteConfig.short_name,
    alternateName: "General-purpose AI Assistant",
    url: siteConfig.url,
    logo: `${siteConfig.url}/images/logos/logo.webp`,
    description: siteConfig.description,
    foundingDate: "2024",
    founders: siteConfig.founders.map(
      (founder): Person => ({
        "@type": "Person",
        name: founder.name,
        jobTitle: founder.role,
        sameAs: [founder.twitter, founder.linkedin].filter(Boolean),
      }),
    ),
    sameAs: [
      siteConfig.links.twitter,
      siteConfig.links.github,
      siteConfig.links.linkedin,
      siteConfig.links.youtube,
    ],
    contactPoint: {
      "@type": "ContactPoint",
      contactType: "Customer Support",
      url: `${siteConfig.url}/contact`,
    },
  };
}

/**
 * Generate WebSite structured data (JSON-LD)
 */
export function generateWebSiteSchema(): WithContext<WebSite> {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: siteConfig.short_name,
    alternateName: siteConfig.name,
    url: siteConfig.url,
    description: siteConfig.description,
  };
}

/**
 * Generate WebPage structured data (JSON-LD)
 */
export function generateWebPageSchema(
  title: string,
  description: string,
  url: string,
  breadcrumbs?: Array<{ name: string; url: string }>,
): WithContext<WebPage> {
  const schema: WithContext<WebPage> = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: title,
    description,
    url,
    isPartOf: {
      "@type": "WebSite",
      url: siteConfig.url,
      name: siteConfig.short_name,
    },
  };

  if (breadcrumbs && breadcrumbs.length > 0) {
    schema.breadcrumb = {
      "@type": "BreadcrumbList",
      itemListElement: breadcrumbs.map(
        (crumb, index): ListItem => ({
          "@type": "ListItem",
          position: index + 1,
          name: crumb.name,
          item: crumb.url,
        }),
      ),
    };
  }

  return schema;
}

/**
 * Generate BreadcrumbList structured data (JSON-LD)
 */
export function generateBreadcrumbSchema(
  items: Array<{ name: string; url: string }>,
): WithContext<BreadcrumbList> {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map(
      (item, index): ListItem => ({
        "@type": "ListItem",
        position: index + 1,
        name: item.name,
        item: getCanonicalUrl(item.url),
      }),
    ),
  };
}

/**
 * Generate FAQ structured data (JSON-LD)
 */
export function generateFAQSchema(
  faqs: Array<{ question: string; answer: string }>,
): WithContext<FAQPage> {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map(
      (faq): Question => ({
        "@type": "Question",
        name: faq.question,
        acceptedAnswer: {
          "@type": "Answer",
          text: faq.answer,
        } as Answer,
      }),
    ),
  };
}

/**
 * Generate Product/SoftwareApplication structured data (JSON-LD)
 */
export function generateProductSchema(): WithContext<SoftwareApplication> {
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: siteConfig.short_name,
    applicationCategory: "ProductivityApplication",
    operatingSystem: "Web, Windows, macOS, Linux",
    description: siteConfig.description,
    offers: {
      "@type": "Offer",
      price: "0",
      priceCurrency: "USD",
      availability: "https://schema.org/InStock",
    } as Offer,
    author: {
      "@type": "Organization",
      name: siteConfig.short_name,
      url: siteConfig.url,
    } as Organization,
  };
}

/**
 * Generate Article/BlogPosting structured data (JSON-LD)
 */
export function generateArticleSchema(
  title: string,
  description: string,
  url: string,
  image: string,
  publishedDate: string,
  modifiedDate: string,
  authors: Array<{ name: string; url?: string }>,
  category?: string,
): WithContext<Article> {
  return {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: title,
    description,
    image,
    url,
    datePublished: publishedDate,
    dateModified: modifiedDate,
    author: authors.map(
      (author): Person => ({
        "@type": "Person",
        name: author.name,
        url: author.url,
      }),
    ),
    publisher: {
      "@type": "Organization",
      name: siteConfig.short_name,
      logo: {
        "@type": "ImageObject",
        url: `${siteConfig.url}/images/logos/logo.webp`,
      } as ImageObject,
    } as Organization,
    mainEntityOfPage: {
      "@type": "WebPage",
      "@id": url,
    } as WebPage,
    ...(category && { articleSection: category }),
  };
}

/**
 * Generate HowTo structured data for tutorials/workflows (JSON-LD)
 */
export function generateHowToSchema(
  name: string,
  description: string,
  steps: Array<{ name: string; text: string; image?: string }>,
): WithContext<HowTo> {
  return {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name,
    description,
    step: steps.map(
      (step, index): HowToStep => ({
        "@type": "HowToStep",
        position: index + 1,
        name: step.name,
        text: step.text,
        ...(step.image && {
          image: step.image,
        }),
      }),
    ),
  };
}

/**
 * Generate ItemList structured data for list pages (JSON-LD)
 */
export function generateItemListSchema(
  items: Array<{ name: string; url: string; description?: string }>,
  listType: "BlogPosting" | "Article" | "Product" = "BlogPosting",
): WithContext<ItemList> {
  return {
    "@context": "https://schema.org",
    "@type": "ItemList",
    itemListElement: items.map(
      (item, index): ListItem => ({
        "@type": "ListItem",
        position: index + 1,
        item: {
          "@type": listType,
          name: item.name,
          url: item.url,
          ...(item.description && { description: item.description }),
        },
      }),
    ),
  };
}

/**
 * Generate ContactPage structured data (JSON-LD)
 */
export function generateContactPageSchema(): WithContext<ContactPage> {
  return {
    "@context": "https://schema.org",
    "@type": "ContactPage",
    name: "Contact GAIA",
    description: "Get in touch with the GAIA team",
    url: `${siteConfig.url}/contact`,
    mainEntity: {
      "@type": "Organization",
      name: siteConfig.short_name,
      url: siteConfig.url,
      contactPoint: {
        "@type": "ContactPoint",
        contactType: "Customer Support",
        url: `${siteConfig.url}/contact`,
        availableLanguage: ["English"],
      } as ContactPoint,
    } as Organization,
  };
}

/**
 * Generate AboutPage structured data (JSON-LD)
 */
export function generateAboutPageSchema(): WithContext<AboutPage> {
  return {
    "@context": "https://schema.org",
    "@type": "AboutPage",
    name: "About GAIA",
    description: "Learn about GAIA's mission and the team behind it",
    url: `${siteConfig.url}/manifesto`,
    mainEntity: {
      "@type": "Organization",
      name: siteConfig.short_name,
      description: siteConfig.description,
      url: siteConfig.url,
      founders: siteConfig.founders.map(
        (founder): Person => ({
          "@type": "Person",
          name: founder.name,
          jobTitle: founder.role,
        }),
      ),
    } as Organization,
  };
}
