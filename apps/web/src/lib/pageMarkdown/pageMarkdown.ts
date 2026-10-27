/** Resolve a page path to its markdown variant, served at `/<path>.md` (the homepage at `/index.md`). */

import { homepageFAQs } from "@/lib/faq";
import { MARKETING_PAGES } from "@/lib/marketingPages";
import { siteConfig } from "@/lib/seo";
import messages from "@/messages/en.json";

import { renderFamilyPage } from "./families";
import { document, faqSection, link, oneLine } from "./markdown";

/** The path segment that names the homepage's variant: `/index.md`, the conventional probe for a site's markdown. */
export const HOMEPAGE_MARKDOWN_SEGMENT = "index";

export interface PageMarkdown {
  /** The HTML page this markdown represents. */
  canonicalUrl: string;
  body: string;
}

function renderHomepage(): string {
  return document([
    `# ${siteConfig.short_name}`,
    `> ${siteConfig.description}`,
    "## Pages",
    MARKETING_PAGES.filter((page) => page.path !== "")
      .map(
        (page) =>
          `- ${link(page.title, `${siteConfig.url}${page.path}`)}: ${oneLine(page.description)}`,
      )
      .join("\n"),
    `Full page index: ${siteConfig.url}/llms.txt`,
    faqSection(messages.common.faq, homepageFAQs),
  ]);
}

/** The markdown variant of the page at `segments`, or undefined when it has none. */
export async function getPageMarkdown(
  segments: readonly string[],
): Promise<PageMarkdown | undefined> {
  if (segments.length === 1 && segments[0] === HOMEPAGE_MARKDOWN_SEGMENT) {
    return { canonicalUrl: siteConfig.url, body: renderHomepage() };
  }
  if (segments.length !== 2) return undefined;
  const [family, slug] = segments;
  const body = await renderFamilyPage(family, slug);
  return body === undefined
    ? undefined
    : { canonicalUrl: `${siteConfig.url}/${family}/${slug}`, body };
}
