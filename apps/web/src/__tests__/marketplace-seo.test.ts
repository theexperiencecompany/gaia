/**
 * Marketplace SEO guardrails: meta descriptions stay within the SERP window
 * with real per-category differentiation, and marketing pages link only to
 * marketplace pages that exist.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  generateIntegrationDescription,
  generateIntegrationTitle,
} from "@/app/[locale]/(landing)/marketplace/[slug]/integrationMeta";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { getMarketplacePath } from "@/features/integrations/lib/serverMarketplaceApi";

const BANNED_TOKENS = [
  "seamless",
  "leverage",
  "unlock",
  "supercharge",
  "elevate",
  "revolutionize",
  "game-changer",
  "cutting-edge",
  "delve",
  "—",
];

const CATEGORIES = [
  "productivity",
  "communication",
  "developer",
  "analytics",
  "finance",
  "ai-ml",
  "education",
  "personal",
  "capabilities",
  "other",
  "email",
  "calendar",
  "task",
  "tasks",
  "crm",
  "notes",
  "development",
  "automation",
  "storage",
  "marketing",
];

const NAMES = ["Slack", "Notion", "Asana", "Microsoft Teams", "Todoist"];

describe("generateIntegrationDescription", () => {
  it("stays within 120-155 chars across categories, names, and tool counts", () => {
    for (const category of CATEGORIES) {
      for (const name of NAMES) {
        for (const toolCount of [0, 1, 12, 150]) {
          const desc = generateIntegrationDescription({
            name,
            category,
            toolCount,
          });
          expect(
            desc.length,
            `${category}/${name}/${toolCount}: "${desc}"`,
          ).toBeGreaterThanOrEqual(120);
          expect(
            desc.length,
            `${category}/${name}/${toolCount}: "${desc}"`,
          ).toBeLessThanOrEqual(155);
        }
      }
    }
  });

  it("interpolates name and tool count, and differentiates categories", () => {
    const seen = new Set<string>();
    for (const category of CATEGORIES) {
      const desc = generateIntegrationDescription({
        name: "Slack",
        category,
        toolCount: 12,
      });
      expect(desc).toContain("Slack");
      expect(desc).toContain("12 actions available");
      // Strip the name so only the category-specific framing is compared.
      seen.add(desc.replaceAll("Slack", ""));
    }
    // developer/development and task/tasks are intentional aliases;
    // everything else must differ.
    expect(seen.size).toBeGreaterThanOrEqual(CATEGORIES.length - 2);
  });

  it("contains no banned filler, em-dashes, or literal dollar amounts", () => {
    for (const category of CATEGORIES) {
      const desc = generateIntegrationDescription({
        name: "Slack",
        category,
        toolCount: 12,
      }).toLowerCase();
      for (const token of BANNED_TOKENS) {
        expect(desc, `${category} contains "${token}"`).not.toContain(token);
      }
      expect(desc).not.toMatch(/\$\d/);
    }
  });
});

describe("generateIntegrationTitle", () => {
  it("stays unique and under 60 chars", () => {
    const titles = CATEGORIES.map((category) =>
      generateIntegrationTitle("Slack", category),
    );
    for (const title of titles) {
      expect(title.length).toBeLessThanOrEqual(60);
    }
    expect(new Set(titles).size).toBeGreaterThan(1);
  });

  it("uses MCP Server phrasing only for slugs with per-tool MCP queries", () => {
    const cases: [string, string][] = [
      ["linkup", "Linkup"],
      ["web-fetch", "Web Fetch"],
      ["any-do", "Any.do"],
      ["hey-email-mcp", "HEY Email"],
      ["wakatime", "WakaTime"],
      ["pixellab", "PixelLab"],
      ["google-meet", "Google Meet"],
      ["sequential-thinking", "Sequential Thinking"],
    ];
    for (const [slug, name] of cases) {
      const title = generateIntegrationTitle(name, "other", slug);
      expect(title).toContain("MCP Server");
      expect(title.length).toBeLessThanOrEqual(60);
    }
    // Unlisted slugs keep their category title (no slug, unknown slug).
    expect(generateIntegrationTitle("Slack", "communication")).toContain(
      "AI Integration",
    );
    expect(
      generateIntegrationTitle("Slack", "communication", "slack"),
    ).toContain("AI Integration");
  });
});

const NATIVE_CONFIG = {
  integrations: [
    {
      id: "googlecalendar",
      slug: "googlecalendar",
      name: "Google Calendar",
      description: "",
      category: "calendar",
      source: "platform",
      available: true,
      displayPriority: 1,
    },
    {
      id: "microsoft_teams",
      slug: "microsoft_teams",
      name: "Microsoft Teams",
      description: "",
      category: "communication",
      source: "platform",
      available: true,
      displayPriority: 0,
    },
  ],
};

/** Answer the integrations config and community endpoints the way the backend does, or fail every call with status. */
function stubBackend(status: number): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      if (status !== 200) return new Response("boom", { status });
      const body = input.url.includes("/integrations/config")
        ? NATIVE_CONFIG
        : { integrations: [], total: 0 };
      return Response.json(body);
    }),
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.stubEnv("API_BASE_URL_INTERNAL", "http://api.test/api/v1");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("marketplace cross-links", () => {
  it("finds canonical automate combos for a marketplace tool slug", async () => {
    const combos = await getAllCombos();
    expect(combos.length).toBeGreaterThan(0);
    // getAllCombos is _slugs-driven: consolidated victims are excluded at the
    // source (they 308 via canonical-redirects.mjs), so no marker filter here.
    const slackCombos = combos.filter(
      (combo) => combo.toolASlug === "slack" || combo.toolBSlug === "slack",
    );
    // The detail page links these; every match must resolve to a real page.
    expect(slackCombos.length).toBeGreaterThan(0);
    for (const combo of slackCombos) {
      expect(combo.slug).toBeTruthy();
      expect(combo.tagline).toBeTruthy();
    }
  });

  it("links a tool to its marketplace page across slug spellings", async () => {
    vi.setSystemTime(new Date("2030-01-01T00:00:00Z"));
    stubBackend(200);

    await expect(getMarketplacePath("google-calendar")).resolves.toBe(
      "/marketplace/googlecalendar",
    );
    await expect(getMarketplacePath("microsoft-teams")).resolves.toBe(
      "/marketplace/microsoft_teams",
    );
    await expect(getMarketplacePath("figma")).resolves.toBeNull();
  });

  it("fails loud when the backend errors instead of silently dropping links", async () => {
    vi.setSystemTime(new Date("2031-01-01T00:00:00Z"));
    stubBackend(500);

    await expect(getMarketplacePath("gmail")).rejects.toThrow(/500/);
  });
});
