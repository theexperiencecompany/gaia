import { describe, expect, it } from "vitest";

import { GET } from "@/app/agent.txt/route";

describe("GET /agent.txt", () => {
  it("serves text/plain with public caching", async () => {
    const response = await GET();
    expect(response.headers.get("Content-Type")).toBe(
      "text/plain; charset=utf-8",
    );
    expect(response.headers.get("Cache-Control")).toContain("public");
  });

  it("contains explicit when-to-use guidance and integration pointers", async () => {
    const body = await (await GET()).text();
    expect(body).toContain("WHEN TO USE");
    expect(body).toContain("WHEN NOT TO USE");
    expect(body).toContain("/llms.txt");
    // MCP surfaces were deliberately removed from agent-facing copy.
    expect(body).not.toContain("/mcp");
    expect(body).toContain("Accept: text/markdown");
  });

  it("only references well-formed absolute https URLs", async () => {
    const body = await (await GET()).text();
    const urls = [...body.matchAll(/https:\/\/\S+/g)].map((m) => m[0]);
    expect(urls.length).toBeGreaterThan(0);
    for (const url of urls) {
      expect(() => new URL(url)).not.toThrow();
    }
  });

  it("stays a concise briefing under 80 lines", async () => {
    const body = await (await GET()).text();
    const lineCount = body.split("\n").length;
    expect(lineCount).toBeGreaterThan(0);
    expect(lineCount).toBeLessThanOrEqual(80);
  });

  it("lists the support contact", async () => {
    const body = await (await GET()).text();
    expect(body).toMatch(/^Support: support@heygaia\.io$/m);
  });
});
