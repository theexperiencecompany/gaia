/** Markdown variants (/<path>.md, served by /md/[...path]) mirror their HTML page's data, stay out of the index, and exist only for covered pages. */
import { existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { GET as getAgentsMd } from "@/app/AGENTS.md/route";
import { GET as getMarkdown } from "@/app/md/[...path]/route";
import { getAlternative } from "@/features/alternatives/data/alternativesData";
import { getComparison } from "@/features/comparisons/data/comparisonsData";
import { getGlossaryTerm } from "@/features/glossary/data/glossaryData";
import { getCombo } from "@/features/integrations/data/combosData";
import { getBlogPost } from "@/lib/blog";
import { homepageFAQs } from "@/lib/faq";
import { siteConfig } from "@/lib/seo";

const BASE_URL = siteConfig.url;
const APP_DIR = path.join(process.cwd(), "src", "app");
const LANDING_DIR = path.join(APP_DIR, "[locale]", "(landing)");
const DOCS_DIR = path.join(process.cwd(), "..", "..", "docs");
const REPO_ROOT = path.join(process.cwd(), "..", "..");

/** Request the markdown variant of a page path, as the `/:path+.md` rewrite hands it to the route. */
function fetchMarkdown(pagePath: string): Promise<Response> {
  const segments = pagePath.split("/").filter(Boolean);
  return getMarkdown(new Request(`${BASE_URL}/${pagePath}.md`), {
    params: Promise.resolve({ path: segments }),
  });
}

async function expectMarkdownFor(
  pagePath: string,
  htmlUrl: string,
): Promise<string> {
  const response = await fetchMarkdown(pagePath);
  expect(response.status).toBe(200);
  expect(response.headers.get("Content-Type")).toBe(
    "text/markdown; charset=utf-8",
  );
  expect(response.headers.get("X-Robots-Tag")).toBe("noindex");
  expect(response.headers.get("Link")).toBe(`<${htmlUrl}>; rel="canonical"`);
  return response.text();
}

describe("GET /<path>.md", () => {
  it("renders the homepage from its description and visible FAQ", async () => {
    const body = await expectMarkdownFor("index", BASE_URL);
    expect(body.startsWith(`# ${siteConfig.short_name}\n`)).toBe(true);
    expect(body).toContain(siteConfig.description);
    for (const faq of homepageFAQs) {
      expect(body).toContain(`### ${faq.question}\n\n${faq.answer}`);
    }
    expect(body).toContain(`](${BASE_URL}/pricing)`);
  });

  it("renders a comparison from its data", async () => {
    const data = await getComparison("chatgpt");
    if (!data) throw new Error("fixture comparison missing");
    const body = await expectMarkdownFor(
      "compare/chatgpt",
      `${BASE_URL}/compare/chatgpt`,
    );
    expect(body.startsWith(`# GAIA vs ${data.name}\n`)).toBe(true);
    expect(body).toContain("## Feature Comparison");
    expect(body).toContain(
      `| ${data.rows[0].feature} | ${data.rows[0].gaia} | ${data.rows[0].competitor} |`,
    );
    expect(body).toContain(`## Where ${data.name} Excels`);
    expect(body).toContain(`- ${data.gaiaAdvantages[0]}`);
    expect(body).toContain(data.verdict.split("\n\n")[0]);
    expect(body).toContain(`### ${data.faqs[0].question}`);
  });

  it("renders an alternative from its data", async () => {
    const data = await getAlternative("notion");
    if (!data) throw new Error("fixture alternative missing");
    const body = await expectMarkdownFor(
      "alternative-to/notion",
      `${BASE_URL}/alternative-to/notion`,
    );
    expect(body).toContain(`# Best ${data.name} Alternative`);
    expect(body).toContain(data.tagline);
    expect(body).toContain(`${data.gaiaFitScore}/5`);
    expect(body).toContain(`1. ${data.migrationSteps[0]}`);
    expect(body).toContain(`- ${data.painPoints[0]}`);
    expect(body).toContain(`### ${data.faqs[0].question}`);
  });

  it("renders a glossary term from its data", async () => {
    const data = await getGlossaryTerm("ai-agent");
    if (!data) throw new Error("fixture term missing");
    const body = await expectMarkdownFor(
      "learn/ai-agent",
      `${BASE_URL}/learn/ai-agent`,
    );
    expect(body.startsWith(`# ${data.term}\n`)).toBe(true);
    expect(body).toContain(data.definition);
    expect(body).toContain(`## Understanding ${data.term}`);
    expect(body).toContain(`## How GAIA Uses ${data.term}`);
  });

  it("renders an automation combo from its data", async () => {
    const data = await getCombo("gmail-slack");
    if (!data) throw new Error("fixture combo missing");
    const body = await expectMarkdownFor(
      "automate/gmail-slack",
      `${BASE_URL}/automate/gmail-slack`,
    );
    expect(body).toContain(
      `# Automate ${data.toolA} + ${data.toolB} with GAIA`,
    );
    expect(body).toContain(
      `## ${data.useCases.length} things you can automate`,
    );
    expect(body).toContain(`### ${data.useCases[0].title}`);
    expect(body).toContain(`### 1. ${data.howItWorks[0].step}`);
  });

  it("renders a blog post from its MDX source", async () => {
    const post = await getBlogPost("how-tool-calling-works");
    if (!post) throw new Error("fixture post missing");
    const body = await expectMarkdownFor(
      "blog/how-tool-calling-works",
      `${BASE_URL}/blog/how-tool-calling-works`,
    );
    expect(body.startsWith(`# ${post.title}\n`)).toBe(true);
    expect(body).toContain(post.authors[0].name);
    expect(body).toContain(post.content.trim().split("\n\n")[0]);
  });

  it.each([
    ["a page family with no markdown variant", "pricing"],
    ["a persona page, whose English HTML is bespoke", "for/startup-founders"],
    ["an unknown slug", "compare/not-a-real-tool"],
    ["a consolidated victim that 308s", "compare/sunsama"],
    ["a path that escapes the data directory", "compare/../glossary/ai-agent"],
    ["a nested path under a family", "compare/chatgpt/extra"],
    ["a family hub", "compare"],
  ])("404s for %s", async (_label, pagePath) => {
    const response = await fetchMarkdown(pagePath);
    expect(response.status).toBe(404);
  });
});

/** Whether a same-site path is served: a markdown variant, an app route, or a landing page. */
async function siteRouteResolves(pathname: string): Promise<boolean> {
  if (pathname.endsWith(".md")) {
    const response = await fetchMarkdown(pathname.slice(1, -".md".length));
    return response.status === 200;
  }
  if (pathname === "/sitemap.xml") {
    return existsSync(path.join(APP_DIR, "api", "sitemap-xml", "route.ts"));
  }
  return (
    existsSync(path.join(APP_DIR, pathname, "route.ts")) ||
    existsSync(path.join(LANDING_DIR, pathname, "page.tsx"))
  );
}

describe("GET /AGENTS.md", () => {
  it("serves markdown that is not indexed", async () => {
    const response = getAgentsMd();
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe(
      "text/markdown; charset=utf-8",
    );
    expect(response.headers.get("X-Robots-Tag")).toBe("noindex");
    const body = await response.text();
    expect(body.startsWith(`# ${siteConfig.short_name}\n`)).toBe(true);
  });

  it("links only to routes, docs pages and repo files that exist", async () => {
    const body = await getAgentsMd().text();
    const links = [...body.matchAll(/\]\(([^)]+)\)/g)].map((m) => m[1]);
    expect(links.length).toBeGreaterThan(8);

    for (const link of links) {
      const url = new URL(link);
      if (url.origin === BASE_URL) {
        expect(await siteRouteResolves(url.pathname), link).toBe(true);
      } else if (url.origin === "https://docs.heygaia.io") {
        const page = url.pathname === "/" ? "/introduction" : url.pathname;
        expect(existsSync(path.join(DOCS_DIR, `${page}.mdx`)), link).toBe(true);
      } else if (link.startsWith(`${siteConfig.links.repo}/blob/master/`)) {
        const file = link.slice(`${siteConfig.links.repo}/blob/master/`.length);
        expect(existsSync(path.join(REPO_ROOT, file)), link).toBe(true);
      } else {
        expect(link).toBe(siteConfig.links.repo);
      }
    }
  });
});
