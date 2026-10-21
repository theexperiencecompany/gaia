/**
 * Structured-data parity tests: every FAQPage schema emitted must match
 * visible FAQs, and every Article dateModified must reflect reality.
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
  generateArticleSchema,
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateItemListSchema,
  generateProductSchema,
} from "@/lib/seo";

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
