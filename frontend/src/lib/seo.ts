import type { Metadata } from "next";

// Site-wide SEO Configuration
export const siteConfig = {
  name: "GAIA",
  fullName: "GAIA - General-purpose AI Assistant",
  description:
    "GAIA is your personal AI assistant designed to boost productivity. Automate tasks, manage emails, schedule meetings, track goals, and handle your daily workflow with intelligent automation.",
  url: "https://heygaia.io",
  ogImage: "/images/screenshot.webp",
  links: {
    twitter: "https://x.com/_heygaia",
    github: "https://github.com/heygaia",
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
  return `${siteConfig.url}${cleanPath}`;
}

/**
 * Generate comprehensive page metadata with SEO best practices
 */
export interface PageMetadataOptions {
  title: string;
  description: string;
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
  description,
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
  const fullTitle =
    title === siteConfig.name ? title : `${title} | ${siteConfig.name}`;
  const allKeywords = [...commonKeywords, ...keywords];

  const metadata: Metadata = {
    title,
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
          url: image,
          width: 1200,
          height: 630,
          alt: `${title} - ${siteConfig.name}`,
        },
      ],
      locale: "en_US",
      type,
    },
    twitter: {
      card: "summary_large_image",
      title: fullTitle,
      description,
      images: [image],
      creator: "@_heygaia",
      site: "@_heygaia",
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
export function generateOrganizationSchema() {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: siteConfig.name,
    alternateName: "General-purpose AI Assistant",
    url: siteConfig.url,
    logo: `${siteConfig.url}/images/logos/logo.webp`,
    description: siteConfig.description,
    foundingDate: "2024",
    founders: siteConfig.founders.map((founder) => ({
      "@type": "Person",
      name: founder.name,
      jobTitle: founder.role,
      sameAs: [founder.twitter, founder.linkedin].filter(Boolean),
    })),
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
export function generateWebSiteSchema() {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: siteConfig.name,
    alternateName: siteConfig.fullName,
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
) {
  const schema: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: title,
    description,
    url,
    isPartOf: {
      "@type": "WebSite",
      url: siteConfig.url,
      name: siteConfig.name,
    },
  };

  if (breadcrumbs && breadcrumbs.length > 0) {
    schema.breadcrumb = {
      "@type": "BreadcrumbList",
      itemListElement: breadcrumbs.map((crumb, index) => ({
        "@type": "ListItem",
        position: index + 1,
        name: crumb.name,
        item: crumb.url,
      })),
    };
  }

  return schema;
}

/**
 * Generate BreadcrumbList structured data (JSON-LD)
 */
export function generateBreadcrumbSchema(
  items: Array<{ name: string; url: string }>,
) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      item: getCanonicalUrl(item.url),
    })),
  };
}

/**
 * Generate FAQ structured data (JSON-LD)
 */
export function generateFAQSchema(
  faqs: Array<{ question: string; answer: string }>,
) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((faq) => ({
      "@type": "Question",
      name: faq.question,
      acceptedAnswer: {
        "@type": "Answer",
        text: faq.answer,
      },
    })),
  };
}

/**
 * Generate Product/SoftwareApplication structured data (JSON-LD)
 */
export function generateProductSchema() {
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: siteConfig.name,
    applicationCategory: "ProductivityApplication",
    operatingSystem: "Web, Windows, macOS, Linux",
    description: siteConfig.description,
    offers: {
      "@type": "Offer",
      price: "0",
      priceCurrency: "USD",
      availability: "https://schema.org/InStock",
    },
    author: {
      "@type": "Organization",
      name: siteConfig.name,
      url: siteConfig.url,
    },
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
) {
  return {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: title,
    description,
    image,
    url,
    datePublished: publishedDate,
    dateModified: modifiedDate,
    author: authors.map((author) => ({
      "@type": "Person",
      name: author.name,
      url: author.url,
    })),
    publisher: {
      "@type": "Organization",
      name: siteConfig.name,
      logo: {
        "@type": "ImageObject",
        url: `${siteConfig.url}/images/logos/logo.webp`,
      },
    },
    mainEntityOfPage: {
      "@type": "WebPage",
      "@id": url,
    },
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
) {
  return {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name,
    description,
    step: steps.map((step, index) => ({
      "@type": "HowToStep",
      position: index + 1,
      name: step.name,
      text: step.text,
      ...(step.image && {
        image: step.image,
      }),
    })),
  };
}

/**
 * Generate ItemList structured data for list pages (JSON-LD)
 */
export function generateItemListSchema(
  items: Array<{ name: string; url: string; description?: string }>,
  listType: "BlogPosting" | "Article" | "Product" = "BlogPosting",
) {
  return {
    "@context": "https://schema.org",
    "@type": "ItemList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      item: {
        "@type": listType,
        name: item.name,
        url: item.url,
        ...(item.description && { description: item.description }),
      },
    })),
  };
}

/**
 * Generate ContactPage structured data (JSON-LD)
 */
export function generateContactPageSchema() {
  return {
    "@context": "https://schema.org",
    "@type": "ContactPage",
    name: "Contact GAIA",
    description: "Get in touch with the GAIA team",
    url: `${siteConfig.url}/contact`,
    mainEntity: {
      "@type": "Organization",
      name: siteConfig.name,
      url: siteConfig.url,
      contactPoint: {
        "@type": "ContactPoint",
        contactType: "Customer Support",
        url: `${siteConfig.url}/contact`,
        availableLanguage: ["English"],
      },
    },
  };
}

/**
 * Generate AboutPage structured data (JSON-LD)
 */
export function generateAboutPageSchema() {
  return {
    "@context": "https://schema.org",
    "@type": "AboutPage",
    name: "About GAIA",
    description: "Learn about GAIA's mission and the team behind it",
    url: `${siteConfig.url}/manifesto`,
    mainEntity: {
      "@type": "Organization",
      name: siteConfig.name,
      description: siteConfig.description,
      url: siteConfig.url,
      founders: siteConfig.founders.map((founder) => ({
        "@type": "Person",
        name: founder.name,
        jobTitle: founder.role,
      })),
    },
  };
}
