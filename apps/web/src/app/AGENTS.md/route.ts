/**
 * GET /AGENTS.md — where an agent finds GAIA's machine-readable surfaces,
 * docs and source. Every link is checked against the route tree, docs/ and
 * the repo by page-markdown.test.ts.
 */

import { MARKDOWN_FAMILY_NAMES } from "@/lib/pageMarkdown/families";
import {
  bulletList,
  document,
  link,
  MARKDOWN_CONTENT_TYPE,
} from "@/lib/pageMarkdown/markdown";
import { HOMEPAGE_MARKDOWN_SEGMENT } from "@/lib/pageMarkdown/pageMarkdown";
import { siteConfig } from "@/lib/seo";

export const dynamic = "force-static";

const BASE_URL = siteConfig.url;
const DOCS_URL = "https://docs.heygaia.io";

function buildBody(): string {
  const familyPatterns = MARKDOWN_FAMILY_NAMES.map(
    (family) => `\`${BASE_URL}/${family}/<slug>.md\``,
  ).join(", ");

  return document([
    `# ${siteConfig.short_name}`,
    `> ${siteConfig.description}`,
    `This is the marketing site and web app at ${BASE_URL}.`,
    "## Machine-readable content",
    bulletList([
      `${link("llms.txt", `${BASE_URL}/llms.txt`)}: index of every public page with a one-line summary.`,
      `Markdown variants: append \`.md\` to a page URL. The homepage is ${link("index.md", `${BASE_URL}/${HOMEPAGE_MARKDOWN_SEGMENT}.md`)}; per-page variants exist for ${familyPatterns}. Other pages have no variant and return 404.`,
      `${link("Sitemap", `${BASE_URL}/sitemap.xml`)}: every indexable URL, in every locale.`,
      `Feeds: ${link("site feed", `${BASE_URL}/feed`)} and ${link("blog RSS", `${BASE_URL}/blog/rss.xml`)}.`,
    ]),
    "## Documentation",
    bulletList([
      `${link("GAIA docs", DOCS_URL)}: using GAIA, its integrations and its bots.`,
      `${link("Adding MCP integrations", `${DOCS_URL}/guides/adding-mcp-integrations`)}: connect MCP servers to GAIA.`,
      `${link("Self-hosting", `${DOCS_URL}/self-hosting/overview`)}: run your own GAIA instance.`,
      `${link("CLI reference", `${DOCS_URL}/self-hosting/cli-reference`)}: the GAIA CLI, installed with \`curl -fsSL ${BASE_URL}/install.sh | sh\` (see ${link("Install GAIA CLI", `${BASE_URL}/cli`)}).`,
      `${link("Developer docs", `${DOCS_URL}/developers/introduction`)}: architecture, local setup and contributing.`,
    ]),
    "## Source code",
    bulletList([
      `${link("theexperiencecompany/gaia", siteConfig.links.repo)}: the source-available monorepo behind this site, the API, the apps and the bots.`,
      `${link("AGENTS.md in the repo", `${siteConfig.links.repo}/blob/master/AGENTS.md`)}: setup, testing and conventions for coding agents working on the codebase.`,
    ]),
  ]);
}

export function GET(): Response {
  return new Response(buildBody(), {
    status: 200,
    headers: {
      "Content-Type": MARKDOWN_CONTENT_TYPE,
      "X-Robots-Tag": "noindex",
    },
  });
}
