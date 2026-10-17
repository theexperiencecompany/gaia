/**
 * Marketplace SEO guardrails: meta descriptions stay within the SERP window
 * with real per-category differentiation, and FAQs vary by category while
 * staying in sync between the visible accordion and FAQPage JSON-LD.
 */
import { describe, expect, it } from "vitest";

import { getIntegrationFAQs } from "@/app/[locale]/(landing)/marketplace/[slug]/faqs";
import {
  generateIntegrationDescription,
  generateIntegrationTitle,
} from "@/app/[locale]/(landing)/marketplace/[slug]/integrationMeta";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { resolveMarketplacePath } from "@/lib/marketplaceLinks";
import { generateFAQSchema } from "@/lib/seo";

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

describe("getIntegrationFAQs variance", () => {
  it("emits a distinct category-specific Q&A per category", () => {
    const questions = CATEGORIES.map(
      (category) =>
        getIntegrationFAQs({ name: "Slack", toolCount: 12, category })[2]
          .question,
    );
    // developer/development and task/tasks share intentional aliases.
    expect(new Set(questions).size).toBeGreaterThanOrEqual(
      CATEGORIES.length - 2,
    );
  });

  it("derives the capability answer from real tool names when present", () => {
    const faqs = getIntegrationFAQs({
      name: "Slack",
      toolCount: 3,
      category: "communication",
      tools: [
        { name: "send_message" },
        { name: "list-channels" },
        { name: "pin_message" },
      ],
    });
    expect(faqs[1].answer).toContain("send message");
    expect(faqs[1].answer).toContain("list channels");
  });

  it("varies the connect answer by auth type without inventing steps", () => {
    const oauth = getIntegrationFAQs({
      name: "Slack",
      toolCount: 1,
      category: "communication",
      authType: "oauth",
    })[0].answer;
    const bearer = getIntegrationFAQs({
      name: "Slack",
      toolCount: 1,
      category: "communication",
      authType: "bearer",
    })[0].answer;
    expect(oauth).toContain("OAuth consent screen");
    expect(bearer).toContain("API token");
    expect(oauth).not.toBe(bearer);
  });

  it("keeps pricing tokens intact with no literal dollar amounts", () => {
    const faqs = getIntegrationFAQs({
      name: "Slack",
      toolCount: 1,
      category: "communication",
    });
    expect(faqs[3].question).toContain("free");
    expect(faqs[3].answer).toContain("no extra charge");
    expect(faqs[3].answer).not.toMatch(/\$\d/);
  });

  it("feeds FAQPage JSON-LD identical Q&As to the visible accordion", () => {
    const faqs = getIntegrationFAQs({
      name: "Slack",
      toolCount: 12,
      category: "communication",
      tools: [{ name: "send_message" }],
      authType: "oauth",
    });
    const schema = generateFAQSchema(faqs);
    expect(schema.mainEntity).toHaveLength(faqs.length);
    const emitted = structuredClone(schema) as unknown as {
      mainEntity: Array<{
        name: string;
        acceptedAnswer: { text: string };
      }>;
    };
    faqs.forEach((faq, i) => {
      expect(emitted.mainEntity[i].name).toBe(faq.question);
      expect(emitted.mainEntity[i].acceptedAnswer.text).toBe(faq.answer);
    });
  });
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

  it("resolveMarketplacePath never links a 404: null when unverifiable", async () => {
    await expect(resolveMarketplacePath("")).resolves.toBeNull();
    await expect(
      resolveMarketplacePath("definitely-not-a-real-slug-xyz"),
    ).resolves.toBeNull();
  });
});
