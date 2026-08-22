import { describe, expect, it } from "vitest";

import { GET } from "@/app/llms.txt/route";

const H1_PATTERN = /^# /gm;
const LINK_LINE_PATTERN = /^- \[[^\]]+\]\(([^)]+)\): (.+)$/gm;

describe("GET /llms.txt", () => {
  it("serves text/plain with public caching", async () => {
    const response = await GET();
    expect(response.headers.get("Content-Type")).toBe(
      "text/plain; charset=utf-8",
    );
    expect(response.headers.get("Cache-Control")).toContain("public");
  });

  it("opens with a single GAIA h1", async () => {
    const body = await (await GET()).text();
    expect(body.startsWith("# GAIA\n")).toBe(true);
    expect(body.match(H1_PATTERN) ?? []).toHaveLength(1);
  });

  it("contains the when-to-use and agent-integration sections", async () => {
    const body = await (await GET()).text();
    expect(body).toContain("## When to use GAIA");
    expect(body).toContain("## Agent integration");
  });

  it("uses absolute https links with non-empty descriptions", async () => {
    const body = await (await GET()).text();
    const linkLines = [...body.matchAll(LINK_LINE_PATTERN)];
    expect(linkLines.length).toBeGreaterThan(0);
    for (const [, url, description] of linkLines) {
      expect(() => new URL(url)).not.toThrow();
      expect(url).toMatch(/^https:\/\//);
      expect(description.trim().length).toBeGreaterThan(0);
    }
  });

  it("references the agent surfaces and sitemaps by URL", async () => {
    const body = await (await GET()).text();
    expect(body).toContain("https://heygaia.io/agent.txt");
    expect(body).toContain("https://heygaia.io/sitemap/0.xml");
    // MCP surfaces were deliberately removed from agent-facing copy.
    expect(body).not.toContain("heygaia.io/mcp");
  });
});
