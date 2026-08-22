import { describe, expect, it } from "vitest";
import {
  generateOrganizationSchema,
  generateWebSiteSchema,
} from "@/lib/seo/organization-schema";

/**
 * Contract for the canonical Organization/WebSite JSON-LD emitted once on the
 * homepage. Audit check #15 ("Organization schema completeness"): the schema
 * must carry every fact that actually exists (legalName, support email,
 * contactPoint) and none that doesn't — no address, no telephone, no
 * fabricated SearchAction. See the builder's doc comment for the decisions.
 */

/** Serializes exactly the way <JsonLd> will, and gives plain-JSON typing. */
function asJson(schema: object): Record<string, unknown> {
  return JSON.parse(JSON.stringify(schema)) as Record<string, unknown>;
}

/** Recursively collect every object key in the value tree. */
function collectKeys(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap(collectKeys);
  if (typeof value === "object" && value !== null) {
    return Object.entries(value).flatMap(([key, val]) => [
      key,
      ...collectKeys(val),
    ]);
  }
  return [];
}

/** Recursively collect every string leaf in the value tree. */
function collectStrings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(collectStrings);
  if (typeof value === "object" && value !== null) {
    return Object.values(value).flatMap(collectStrings);
  }
  return [];
}

describe("generateOrganizationSchema", () => {
  const organization = asJson(generateOrganizationSchema());

  it("declares the correct @context and @type", () => {
    expect(organization["@context"]).toBe("https://schema.org");
    expect(organization["@type"]).toBe("Organization");
    expect(organization["@id"]).toBe("https://heygaia.io/#organization");
  });

  it("carries the exact legal name confirmed by the founder", () => {
    expect(organization["legalName"]).toBe("The Experience Comp, Inc.");
  });

  it("exposes the canonical support email at entity and contactPoint level", () => {
    expect(organization["email"]).toBe("support@heygaia.io");
    expect(organization["contactPoint"]).toEqual({
      "@type": "ContactPoint",
      contactType: "customer support",
      email: "support@heygaia.io",
    });
  });

  it("never claims a postal address or phone line (deliberate product decision)", () => {
    const keys = collectKeys(organization);
    expect(keys).not.toContain("address");
    expect(keys).not.toContain("postalAddress");
    expect(keys).not.toContain("telephone");
    // security@ is real but belongs to security disclosures, not support.
    expect(collectStrings(organization)).not.toContain("security@heygaia.io");
  });

  it("keeps every identity field present with a real, non-empty value", () => {
    for (const field of [
      organization["name"],
      organization["url"],
      organization["logo"],
      organization["image"],
      organization["description"],
      organization["slogan"],
    ]) {
      expect(field).toBeTruthy();
    }
    expect(organization["name"]).toBe("GAIA");
    expect(organization["url"]).toBe("https://heygaia.io");

    for (const str of collectStrings(organization)) {
      expect(str.trim().length).toBeGreaterThan(0);
    }

    // Logo must be an absolute URL to a real brand asset (2442x2400 webp).
    const logo = new URL(organization["logo"] as string);
    expect(`${logo.origin}${logo.pathname}`).toBe(
      "https://heygaia.io/images/logos/logo.webp",
    );
  });

  it("lists unique external profiles in sameAs", () => {
    const sameAs = organization["sameAs"] as string[];
    expect(sameAs.length).toBeGreaterThan(0);
    expect(new Set(sameAs).size).toBe(sameAs.length);
    for (const url of sameAs) {
      expect(url.startsWith("https://")).toBe(true);
      // sameAs identifies the org elsewhere; its own homepage lives on `url`.
      expect(url).not.toBe(organization["url"]);
    }
    expect(sameAs).toContain("https://github.com/theexperiencecompany");
  });

  it("describes both founders with their profiles", () => {
    const founders = organization["founders"] as Record<string, unknown>[];
    expect(founders).toHaveLength(2);
    for (const founder of founders) {
      expect(founder["@type"]).toBe("Person");
      expect(String(founder["name"]).length).toBeGreaterThan(0);
      expect(founder["sameAs"] as string[]).toHaveLength(2);
    }
  });

  it("round-trips through JSON.stringify without dropping fields", () => {
    const original = generateOrganizationSchema();
    const parsed = asJson(original);
    // A vanished (undefined) or added key breaks strict key-tree equality.
    expect(collectKeys(parsed)).toStrictEqual(collectKeys(original));
  });
});

describe("generateWebSiteSchema", () => {
  const website = asJson(generateWebSiteSchema());

  it("declares the correct @context and @type with identity fields", () => {
    expect(website["@context"]).toBe("https://schema.org");
    expect(website["@type"]).toBe("WebSite");
    expect(website["name"]).toBe("GAIA");
    expect(website["url"]).toBe("https://heygaia.io");
    expect(String(website["description"]).length).toBeGreaterThan(0);
    expect(String(website["alternateName"]).length).toBeGreaterThan(0);
  });

  it("claims no SearchAction — there is no public site search to back it", () => {
    expect(website["potentialAction"]).toBeUndefined();
    expect(collectKeys(website)).not.toContain("potentialAction");
  });

  it("round-trips through JSON.stringify without dropping fields", () => {
    const original = generateWebSiteSchema();
    const parsed = asJson(original);
    expect(parsed).toStrictEqual(original);
  });
});
