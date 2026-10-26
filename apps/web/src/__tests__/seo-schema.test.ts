/**
 * Structured-data parity tests: every FAQPage schema emitted must match
 * visible FAQs, every Article dateModified must reflect reality, and every
 * entity is one node with a stable @id.
 */
import { describe, expect, it } from "vitest";

import {
  AGENCY_FAQS,
  EM_FAQS,
  FOUNDERS_FAQS,
  PM_FAQS,
  SALES_FAQS,
  SOFTWARE_DEV_FAQS,
} from "@/features/landing/data/personaFaqs";
import {
  ADVERTISED_PRO_MONTHLY,
  ADVERTISED_PRO_MONTHLY_PRICE,
} from "@/features/pricing/advertisedPrice";
import {
  generateAboutPageSchema,
  generateArticleSchema,
  generateBreadcrumbSchema,
  generateContactPageSchema,
  generateDefinedTermSchema,
  generateFAQSchema,
  generateItemListSchema,
  generateOrganizationSchema,
  generateProductSchema,
  generateWebPageSchema,
  generateWebSiteSchema,
  organizationRef,
} from "@/lib/seo";
import type { UseCase } from "@/types/features/workflowTypes";
import { generateUseCaseStructuredData } from "@/utils/seoUtils";

const ROLE_FAQ_SETS = {
  AGENCY_FAQS,
  EM_FAQS,
  FOUNDERS_FAQS,
  PM_FAQS,
  SALES_FAQS,
  SOFTWARE_DEV_FAQS,
} as const;

describe("generateFAQSchema", () => {
  it("emits a valid FAQPage whose mainEntity mirrors the input", () => {
    const schema = generateFAQSchema(AGENCY_FAQS);

    expect(schema["@context"]).toBe("https://schema.org");
    expect(schema["@type"]).toBe("FAQPage");
    expect(schema.mainEntity).toEqual(
      AGENCY_FAQS.map(({ question, answer }) => ({
        "@type": "Question",
        name: question,
        acceptedAnswer: { "@type": "Answer", text: answer },
      })),
    );
  });

  it("every role-page FAQ set is non-empty with non-blank Q&A", () => {
    for (const [name, faqs] of Object.entries(ROLE_FAQ_SETS)) {
      expect(faqs.length, `${name} must not be empty`).toBeGreaterThan(0);
      for (const faq of faqs) {
        expect(faq.question.trim().length, `${name} question`).toBeGreaterThan(
          0,
        );
        expect(faq.answer.trim().length, `${name} answer`).toBeGreaterThan(0);
      }
      // An empty FAQPage is invalid for rich results — the builder output
      // for each role page must carry at least one question.
      const schema = generateFAQSchema([...faqs]);
      expect(schema.mainEntity).toHaveLength(faqs.length);
    }
  });
});

describe("generateItemListSchema", () => {
  it("emits plain positioned ListItems with no typed nested item", () => {
    const schema = generateItemListSchema([
      { name: "GAIA vs Notion", url: "https://heygaia.io/compare/notion" },
      { name: "GAIA", url: "https://heygaia.io" },
    ]);

    expect(schema).toEqual({
      "@context": "https://schema.org",
      "@type": "ItemList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "GAIA vs Notion",
          url: "https://heygaia.io/compare/notion",
        },
        {
          "@type": "ListItem",
          position: 2,
          name: "GAIA",
          url: "https://heygaia.io",
        },
      ],
    });
  });
});

describe("generateBreadcrumbSchema", () => {
  it("emits sequential positions with absolute URLs", () => {
    const schema = generateBreadcrumbSchema([
      { name: "Home", url: "https://heygaia.io" },
      { name: "For Agency Owners", url: "/agency-owners" },
    ]);

    expect(schema["@type"]).toBe("BreadcrumbList");
    expect(schema.itemListElement).toEqual([
      expect.objectContaining({ position: 1 }),
      expect.objectContaining({
        position: 2,
        // Relative input URLs are resolved against the site origin.
        item: "https://heygaia.io/agency-owners",
      }),
    ]);
  });
});

describe("generateArticleSchema", () => {
  it("carries distinct datePublished/dateModified when a revision exists", () => {
    const schema = generateArticleSchema(
      "Title",
      "Description",
      "https://heygaia.io/blog/slug",
      "https://heygaia.io/images/blog/x.webp",
      "2025-12-04",
      "2026-02-10",
      [{ name: "Aryan Randeriya" }],
      "Engineering",
    );

    expect(schema["@type"]).toBe("BlogPosting");
    expect(schema.datePublished).toBe("2025-12-04");
    expect(schema.dateModified).toBe("2026-02-10");
  });

  it("falls back to the publish date when never revised", () => {
    const schema = generateArticleSchema(
      "Title",
      "Description",
      "https://heygaia.io/blog/slug",
      "https://heygaia.io/images/blog/x.webp",
      "2025-12-04",
      "2025-12-04",
      [{ name: "Aryan Randeriya" }],
    );

    expect(schema.datePublished).toBe(schema.dateModified);
  });
});

describe("generateProductSchema", () => {
  it("offers hosted GAIA at the advertised monthly price, not for free", () => {
    const schema = generateProductSchema();

    expect(schema).not.toHaveProperty("isAccessibleForFree");
    expect(schema.offers).toMatchObject({
      "@type": "Offer",
      price: String(ADVERTISED_PRO_MONTHLY_PRICE),
      priceCurrency: ADVERTISED_PRO_MONTHLY.currency,
      priceSpecification: {
        "@type": "UnitPriceSpecification",
        price: String(ADVERTISED_PRO_MONTHLY_PRICE),
        priceCurrency: ADVERTISED_PRO_MONTHLY.currency,
        unitCode: "MON",
      },
    });
  });
});

/** Every schema.org node a page can emit, from each generator a landing page renders. */
function everySchemaNode(): unknown[] {
  return [
    generateOrganizationSchema(),
    generateWebSiteSchema(),
    generateWebPageSchema("Title", "Description", "https://heygaia.io/x"),
    generateProductSchema(),
    generateArticleSchema(
      "Title",
      "Description",
      "https://heygaia.io/blog/slug",
      "https://heygaia.io/images/blog/x.webp",
      "2025-12-04",
      "2025-12-04",
      [{ name: "Aryan Randeriya", url: "https://linkedin.com/in/x" }],
    ),
    generateContactPageSchema(),
    generateAboutPageSchema(),
    generateUseCaseStructuredData({
      title: "Inbox Triage",
      description: "Daily digest of the inbox.",
      action_type: "workflow",
      integrations: [],
      categories: ["featured"],
      published_id: "wf_1",
      slug: "inbox-triage",
      creator: { id: "system", name: "GAIA Team", avatar: null },
    } as UseCase),
    generateUseCaseStructuredData({
      title: "Job Scraper",
      description: "Scrape new engineering job postings.",
      action_type: "workflow",
      integrations: [],
      categories: ["community"],
      published_id: "wf_2",
      slug: "job-scraper-1b2627",
      creator: { id: "user_1", name: "Anurag Bansal", avatar: null },
    } as UseCase),
    generateDefinedTermSchema({
      term: "Agent Loop",
      definition: "An agent loop is the iterative execution cycle.",
      path: "/learn/agent-loop",
      locale: "en",
    }),
  ];
}

/** Every object inside a JSON-LD tree that declares a schema.org type. */
function typedNodes(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) return value.flatMap(typedNodes);
  if (!value || typeof value !== "object") return [];
  const node = value as Record<string, unknown>;
  const children = Object.values(node).flatMap(typedNodes);
  return "@type" in node ? [node, ...children] : children;
}

describe("schema entity identity", () => {
  it("gives every entity that recurs across pages a stable @id", () => {
    const anonymous = typedNodes(everySchemaNode())
      .filter((node) =>
        [
          "Organization",
          "WebSite",
          "Person",
          "DefinedTerm",
          "DefinedTermSet",
        ].includes(String(node["@type"])),
      )
      .filter((node) => !node["@id"])
      .map((node) => `${node["@type"]} ${node.name}`);
    expect(anonymous).toEqual([]);
  });

  it("declares GAIA once and refers to it by @id everywhere else", () => {
    const declared = typedNodes(everySchemaNode()).filter(
      (node) => node["@id"] === organizationRef["@id"],
    );
    expect(declared).toHaveLength(1);
  });

  it("credits GAIA's own workflows to the organization, not a person", () => {
    const useCase = generateUseCaseStructuredData({
      title: "Inbox Triage",
      slug: "inbox-triage",
      creator: { id: "system", name: "GAIA Team", avatar: null },
    } as UseCase);
    expect(useCase.author).toEqual(organizationRef);
  });
});

describe("generateDefinedTermSchema", () => {
  const termIn = (locale: string) =>
    generateDefinedTermSchema({
      term: "Agent Loop",
      definition: `Definition in ${locale}.`,
      path: "/learn/agent-loop",
      locale,
    });

  it("makes each translation its own entity, on its own page", () => {
    const english = termIn("en");
    const portuguese = termIn("pt-BR");

    expect(english).toMatchObject({
      "@id": "https://heygaia.io/learn/agent-loop#term",
      url: "https://heygaia.io/learn/agent-loop",
    });
    expect(portuguese).toMatchObject({
      "@id": "https://heygaia.io/pt-BR/learn/agent-loop#term",
      url: "https://heygaia.io/pt-BR/learn/agent-loop",
    });
    expect(portuguese.inDefinedTermSet).toMatchObject({
      "@id": "https://heygaia.io/pt-BR/learn#glossary",
      url: "https://heygaia.io/pt-BR/learn",
      inLanguage: "pt-BR",
    });
  });
});

describe("generateWebPageSchema", () => {
  it("states no publish or modification date it was not given", () => {
    const schema = generateWebPageSchema(
      "Title",
      "Description",
      "https://heygaia.io/x",
    );
    expect(schema).not.toHaveProperty("datePublished");
    expect(schema).not.toHaveProperty("dateModified");
  });

  it("carries the content dates it is given", () => {
    const schema = generateWebPageSchema(
      "Title",
      "Description",
      "https://heygaia.io/x",
      undefined,
      { published: "2025-11-02", modified: "2026-01-15" },
    );
    expect(schema.datePublished).toBe("2025-11-02");
    expect(schema.dateModified).toBe("2026-01-15");
  });
});
