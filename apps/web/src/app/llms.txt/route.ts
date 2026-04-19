import fs from "fs";
import type { PageInfo } from "next-llms-txt";
import { createLLmsTxt } from "next-llms-txt";

import { siteConfig } from "@/lib/seo";

const BASE_URL = siteConfig.url;

function extractMetadata(
  filePath: string,
): { title: string; description?: string } | null {
  try {
    const content = fs.readFileSync(filePath, "utf-8");
    const titleMatch = content.match(/\btitle:\s*["']([^"'\n]+)["']/);
    if (!titleMatch) return null;
    const descriptionMatch = content.match(
      /\bdescription:\s*["']([^"'\n]+)["']/,
    );
    return {
      title: titleMatch[1],
      description: descriptionMatch?.[1],
    };
  } catch {
    return null;
  }
}

function generateContent(
  _config: unknown,
  pages: PageInfo[] | undefined,
): string {
  const enriched = (pages ?? [])
    .filter((p) => !p.route.includes("["))
    .map((page) => {
      if (page.config?.title) return page;
      const meta = extractMetadata(page.filePath);
      if (!meta) return null;
      return { ...page, config: { ...meta } };
    })
    .filter((p): p is PageInfo => p !== null && !!p.config?.title)
    .sort((a, b) =>
      (a.config?.title ?? "").localeCompare(b.config?.title ?? ""),
    );

  const lines: string[] = [
    `# ${siteConfig.short_name}`,
    "",
    `> ${siteConfig.description}`,
    "",
    "## Pages",
  ];

  for (const page of enriched) {
    const desc = page.config?.description ? `: ${page.config.description}` : "";
    lines.push(`- [${page.config?.title}](${BASE_URL}${page.route})${desc}`);
  }

  return lines.join("\n");
}

export const { GET } = createLLmsTxt({
  baseUrl: BASE_URL,
  defaultConfig: {
    title: siteConfig.short_name,
    description: siteConfig.description,
  },
  autoDiscovery: {
    appDir: "src/app/[locale]/(landing)",
    rootDir: process.cwd(),
  },
  generator: generateContent,
});

export const revalidate = 3600;
