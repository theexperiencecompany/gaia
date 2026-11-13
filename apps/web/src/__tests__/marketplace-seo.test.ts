/**
 * Marketplace SEO guardrails: titles lead with the searched phrase and fit the
 * snippet with the brand suffix, descriptions are grounded in the integration's
 * own use cases and tools, and marketing pages link only to marketplace pages that exist.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  generateIntegrationDescription,
  generateIntegrationTitle,
  type IntegrationMetaInput,
} from "@/app/[locale]/(landing)/marketplace/[slug]/integrationMeta";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { getMarketplacePath } from "@/features/integrations/lib/serverMarketplaceApi";
import { generatePageMetadata } from "@/lib/seo";

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
  "open source",
  "open-source",
  "—",
];

/** Production records (trimmed) from /integrations/public/{slug}. */
const GOOGLE_CALENDAR: IntegrationMetaInput = {
  name: "Google Calendar",
  category: "productivity",
  source: "platform",
  toolCount: 56,
  description: "Schedule meetings and manage your calendar events",
  tools: [
    { name: "GOOGLECALENDAR_ACL_DELETE" },
    { name: "GOOGLECALENDAR_ACL_GET" },
  ],
  content: {
    useCases: [
      "Schedule meetings by describing your availability in plain English, and GAIA books the slot instantly",
      "Get a morning briefing of every event happening today, delivered to your chat",
    ],
  },
};

const INSTACART: IntegrationMetaInput = {
  name: "Instacart",
  category: "lifestyle",
  source: "platform",
  toolCount: 3,
  description:
    "Search and browse grocery products, recipes, and shopping options.",
  tools: [
    { name: "INSTACART_CREATE_RECIPE_PAGE" },
    { name: "INSTACART_CREATE_SHOPPING_LIST_PAGE" },
    { name: "INSTACART_GET_NEARBY_RETAILERS" },
  ],
  content: {
    useCases: [
      "Search for grocery products and find the best options from local stores",
    ],
  },
};

const POSTHOG: IntegrationMetaInput = {
  name: "PostHog",
  category: "business",
  source: "platform",
  toolCount: 1,
  description:
    "Product analytics and experimentation platform - track events, analyze user funnels, run A/B tests, manage feature flags, and query session recordings.",
  tools: [{ name: "exec" }],
  content: {
    useCases: [
      "Query your PostHog analytics data with plain English, like 'how many users signed up this week?'",
    ],
  },
};

const LINKUP: IntegrationMetaInput = {
  name: "Linkup",
  category: "capabilities",
  source: "custom",
  toolCount: 0,
  description:
    "Real-time web search API that provides fresh, accurate results from across the internet with source attribution and content extraction capabilities.",
  tools: [],
  content: {
    useCases: [
      "Retrieve real-time news and current events from across the web",
      "Extract and summarize specific content from live websites",
    ],
  },
};

const PRISMA: IntegrationMetaInput = {
  name: "Prisma",
  category: "developer",
  source: "custom",
  toolCount: 13,
  description:
    "Database management with Prisma ORM - introspect schemas, generate migrations, run type-safe queries, and manage your database directly from the agent.",
  tools: [{ name: "create_prisma_postgres_database" }],
  content: {
    useCases: [
      "Introspect existing database schemas to generate type-safe client code",
    ],
  },
};

const FIXTURES = [GOOGLE_CALENDAR, INSTACART, POSTHOG, LINKUP, PRISMA];

const LONG_NAMES = [
  "Sequential Thinking",
  "Postman Minimal (EU)",
  "Microsoft Dynamics 365 Business Central",
  "Extremely Long Community Server Name That Nobody Would Ever Search For Verbatim",
];

/** Every source and name length the formulas branch on. */
const ALL_INPUTS: IntegrationMetaInput[] = [
  ...FIXTURES,
  ...LONG_NAMES.flatMap((name) => FIXTURES.map((base) => ({ ...base, name }))),
];

/** The title as a result snippet shows it, after the layout's suffix rule. */
function renderedTitle(title: string): string {
  const metadata = generatePageMetadata({ title, path: "/marketplace/x" });
  return String(metadata.openGraph?.title);
}

describe("generateIntegrationTitle", () => {
  it("leads community MCP servers with '<Name> MCP' and platform ones with the searched phrase", () => {
    expect(generateIntegrationTitle(LINKUP)).toBe(
      "Linkup MCP Server: Connect It to Your AI Assistant",
    );
    expect(generateIntegrationTitle(PRISMA)).toBe(
      "Prisma MCP Server: 13 Tools for Your AI Assistant",
    );
    expect(generateIntegrationTitle(GOOGLE_CALENDAR)).toBe(
      "Google Calendar AI: Run 56 Actions from Chat",
    );
    expect(generateIntegrationTitle(INSTACART)).toBe(
      "Automate Instacart with AI: Run 3 Actions from Chat",
    );
    expect(generateIntegrationTitle(POSTHOG)).toBe(
      "Connect PostHog to AI: Ask in Plain English",
    );
  });

  it("keeps the MCP phrasing for a community server named like a platform integration", () => {
    const communityCalendar = { ...GOOGLE_CALENDAR, source: "custom" as const };
    expect(generateIntegrationTitle(communityCalendar)).toMatch(
      /^Google Calendar MCP Server/,
    );
    expect(generateIntegrationTitle(GOOGLE_CALENDAR)).not.toContain("MCP");
  });

  it("renders within 60 characters including the brand suffix, for every source and name length", () => {
    for (const input of ALL_INPUTS) {
      const rendered = renderedTitle(generateIntegrationTitle(input));
      expect(rendered.length, rendered).toBeLessThanOrEqual(60);
      expect(rendered, rendered).not.toMatch(/GAIA \| GAIA/);
    }
  });

  it("drops the subtitle before the brand suffix and the name, as the name grows", () => {
    const sequential = generateIntegrationTitle({
      ...LINKUP,
      name: "Sequential Thinking",
    });
    expect(sequential).toBe("Sequential Thinking MCP Server for AI Assistants");
    expect(renderedTitle(sequential)).toBe(`${sequential} | GAIA`);

    const longest = LONG_NAMES.at(-1) ?? "";
    const trimmed = generateIntegrationTitle({ ...LINKUP, name: longest });
    expect(trimmed.length).toBeLessThanOrEqual(60);
    expect(longest.startsWith(trimmed)).toBe(true);
    expect(trimmed.endsWith(" ")).toBe(false);
  });

  it("is never the old repetitive formula", () => {
    for (const input of FIXTURES) {
      expect(generateIntegrationTitle(input)).not.toMatch(
        /AI Integration: Automate .* Workflows/,
      );
    }
  });
});

describe("generateIntegrationDescription", () => {
  it("stays within 120-160 chars for every source and name length", () => {
    for (const input of ALL_INPUTS) {
      const desc = generateIntegrationDescription(input);
      expect(desc.length, desc).toBeGreaterThanOrEqual(120);
      expect(desc.length, desc).toBeLessThanOrEqual(160);
    }
  });

  it("grounds the copy in the integration's own use case and tools", () => {
    expect(generateIntegrationDescription(GOOGLE_CALENDAR)).toBe(
      "Use Google Calendar with AI in GAIA. Schedule meetings by describing your availability in plain English, and GAIA books the slot instantly. 56 tools available.",
    );
    // The tool list would overflow 160, so it is skipped for the shorter closing line.
    expect(generateIntegrationDescription(INSTACART)).toBe(
      "Automate Instacart with GAIA, your AI assistant. Search for grocery products and find the best options from local stores. Add it to your GAIA from this page.",
    );
    expect(generateIntegrationDescription(PRISMA)).toContain(
      "13 tools available.",
    );
    expect(generateIntegrationDescription(LINKUP)).toMatch(
      /^Connect the Linkup MCP server to GAIA\. Retrieve real-time news/,
    );
  });

  it("names the tools one by one only when there are a few", () => {
    const twoTools = generateIntegrationDescription({
      ...INSTACART,
      toolCount: 2,
      tools: INSTACART.tools?.slice(0, 2),
      content: { useCases: ["Build a list"] },
    });
    expect(twoTools).toContain(
      "Tools: create recipe page, create shopping list page.",
    );
    expect(twoTools).not.toContain("INSTACART_");
    expect(generateIntegrationDescription(GOOGLE_CALENDAR)).not.toContain(
      "acl",
    );
  });

  it("states no tool count the data does not supply", () => {
    expect(generateIntegrationDescription(LINKUP)).not.toMatch(/\d+ tools?/);
    expect(generateIntegrationDescription(POSTHOG)).toContain(
      "1 tool available.",
    );
  });

  it("contains no banned filler, em-dashes, or literal dollar amounts", () => {
    for (const input of ALL_INPUTS) {
      const desc = generateIntegrationDescription(input).toLowerCase();
      for (const token of BANNED_TOKENS) {
        expect(desc, `${input.name} contains "${token}"`).not.toContain(token);
      }
      expect(desc).not.toMatch(/\$\d/);
    }
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
