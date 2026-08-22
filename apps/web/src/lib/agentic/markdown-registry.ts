/**
 * Path → markdown registry consumed by edge middleware.
 *
 * Variants are generated from structured, build-time data — never by
 * scraping HTML or self-fetching pages — because middleware runs on the
 * Cloudflare Workers edge runtime where only pure TS and bundled data are
 * available.
 *
 * Sources per path:
 * - `/`   → `HOME_CONTENT` (hero + sections) + `homepageFAQs`
 * - `/faq` → full `faqData` (mirrors exactly what the /faq page renders)
 *
 * Pages whose data only exists behind runtime API calls (blog index, pricing
 * plans, comparison entries) deliberately have no variant: fetching them from
 * middleware would add an upstream hop to every negotiated request.
 */

import { HOME_CONTENT } from "@/features/landing/content/home-content";
import {
  buildPageMarkdown,
  MARKDOWN_CACHE_CONTROL,
  type MarkdownVariant,
} from "@/lib/agentic/markdown-pages";
import { faqData, homepageFAQs } from "@/lib/faq";
import { siteConfig } from "@/lib/seo";

/** Absolute base URL used in the links block (no trailing slash). */
const BASE_URL = siteConfig.url;

/**
 * Return the markdown variant for a registry pathname, or null when the path
 * has none (caller passes through untouched). Locale-prefixed paths
 * (`/de/faq`) intentionally do not match: variants are English-only, and
 * those URLs keep serving localized HTML via next-intl.
 */
export function getMarkdownVariant(pathname: string): MarkdownVariant | null {
  switch (normalizePathname(pathname)) {
    case "/":
      return { body: buildHomeMarkdown(), cacheHint: MARKDOWN_CACHE_CONTROL };
    case "/faq":
      return { body: buildFaqMarkdown(), cacheHint: MARKDOWN_CACHE_CONTROL };
    default:
      return null;
  }
}

function normalizePathname(pathname: string): string {
  if (pathname.length > 1 && pathname.endsWith("/")) {
    return pathname.slice(0, -1);
  }
  return pathname;
}

function buildHomeMarkdown(): string {
  return buildPageMarkdown({
    title: HOME_CONTENT.heroTitle,
    intro: HOME_CONTENT.heroSubtitle,
    sections: HOME_CONTENT.sections.map((section) => ({
      heading: section.heading,
      description: section.description,
    })),
    faqs: homepageFAQs,
    links: [
      { label: "Pricing", href: `${BASE_URL}/pricing` },
      { label: "Blog", href: `${BASE_URL}/blog` },
      { label: "Machine-readable page index", href: `${BASE_URL}/llms.txt` },
      { label: "Documentation", href: "https://docs.heygaia.io" },
    ],
  });
}

function buildFaqMarkdown(): string {
  return buildPageMarkdown({
    title: "Frequently Asked Questions",
    intro:
      "Answers to common questions about GAIA, your personal AI assistant.",
    faqs: faqData,
  });
}
