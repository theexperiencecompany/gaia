import { describe, expect, it } from "vitest";

import { GET } from "./route";

describe("GET /llms.txt", () => {
  it("lists the full public page index from sitemap data", async () => {
    const response = await GET();
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toContain("text/plain");

    const body = await response.text();

    // Header preserved.
    expect(body).toContain("# GAIA");
    expect(body.startsWith("# GAIA")).toBe(true);

    const entryLines = body
      .split("\n")
      .filter((line) => line.startsWith("- ["));
    expect(entryLines.length).toBeGreaterThan(500);

    // Spot-checks: a learn term, a comparison, an alternative, a combo, a persona.
    for (const url of [
      "https://heygaia.io/learn/ai-agent",
      "https://heygaia.io/compare/chatgpt",
      "https://heygaia.io/alternative-to/notion",
      "https://heygaia.io/automate/gmail-slack",
      "https://heygaia.io/for/startup-founders",
    ]) {
      expect(entryLines.some((line) => line.includes(`](${url})`))).toBe(true);
    }

    // Every entry is a well-formed single-line markdown link with a description.
    for (const line of entryLines) {
      expect(line).toMatch(/^- \[.+?\]\(https:\/\/heygaia\.io[^)]*\): .+$/);
    }
  });
});
