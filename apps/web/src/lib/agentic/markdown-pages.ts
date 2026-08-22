/**
 * Pure markdown page builder for acceptmarkdown.com v2 content negotiation.
 *
 * No app-data imports — callers pass plain structured data, so this module
 * bundles into edge middleware and unit-tests without depending on any
 * content module landing. The registry that wires real site content into it
 * lives in `markdown-registry.ts`.
 */

export const MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8";
export const MARKDOWN_CACHE_CONTROL = "public, max-age=3600";

export interface MarkdownLink {
  label: string;
  href: string;
}

export interface MarkdownSection {
  heading: string;
  description?: string;
}

export interface MarkdownFaq {
  question: string;
  answer: string;
}

/** Structural input for `buildPageMarkdown` — plain data, no imports needed. */
export interface PageMarkdownSource {
  title: string;
  intro?: string;
  sections?: MarkdownSection[];
  faqs?: MarkdownFaq[];
  links?: MarkdownLink[];
}

export interface MarkdownVariant {
  body: string;
  /** Cache-Control header value for the markdown response. */
  cacheHint: string;
}

/**
 * Render a page's structured data as clean markdown: one H1 title, optional
 * intro paragraphs, one H2 per section, an FAQ block of H3 questions with
 * paragraph answers, and a final links list. Blocks with no data are omitted
 * entirely — output contains zero raw HTML because every source field is
 * plain text from trusted build-time data.
 */
export function buildPageMarkdown(source: PageMarkdownSource): string {
  const blocks: string[] = [`# ${source.title}`];

  if (source.intro?.trim()) {
    blocks.push(source.intro.trim());
  }

  for (const section of source.sections ?? []) {
    blocks.push(`## ${section.heading}`);
    if (section.description?.trim()) {
      blocks.push(section.description.trim());
    }
  }

  const faqs = (source.faqs ?? []).filter((f) => f.question && f.answer);
  if (faqs.length > 0) {
    blocks.push("## Frequently asked questions");
    for (const faq of faqs) {
      blocks.push(`### ${faq.question}`, faq.answer);
    }
  }

  if ((source.links ?? []).length > 0) {
    const items = (source.links ?? [])
      .map((link) => `- [${link.label}](${link.href})`)
      .join("\n");
    blocks.push(`## Links\n\n${items}`);
  }

  return `${blocks.join("\n\n")}\n`;
}
