import type {
  ContactPoint,
  Organization,
  Person,
  WebSite,
  WithContext,
} from "schema-dts";

import { siteConfig } from "../seo";

/**
 * Canonical Organization and WebSite JSON-LD for heygaia.io.
 *
 * Google's structured-data guideline: these two entities belong on the
 * homepage (or a single about page), not on every page. The homepage renders
 * them once via <JsonLd>; no other route may emit Organization/WebSite blocks.
 * The builders previously lived in `../seo` and were ALSO rendered sitewide
 * by `[locale]/layout.tsx` — that duplication is gone.
 *
 * Deliberately absent (do not "fix" without a real value):
 * - `address` / `foundingLocation` — no postal address exists; never fabricate one.
 * - `telephone` — no support phone line exists.
 * - `potentialAction` SearchAction — there is no public site search at
 *   `/use-cases?q=`; structured data must not claim functionality that
 *   doesn't exist.
 * - `security@heygaia.io` is a real inbox but belongs to security disclosures,
 *   not customer support, so it is intentionally not a contactPoint.
 */

/** The only support inbox. Canonical domain is heygaia.io. */
const SUPPORT_EMAIL = "support@heygaia.io";

const supportContactPoint: ContactPoint = {
  "@type": "ContactPoint",
  contactType: "customer support",
  email: SUPPORT_EMAIL,
};

export function generateOrganizationSchema(): WithContext<Organization> {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    "@id": `${siteConfig.url}/#organization`,
    name: siteConfig.short_name,
    legalName: "The Experience Comp, Inc.",
    alternateName: [
      "GAIA AI",
      "GAIA AI Assistant",
      "Hey GAIA",
      "GAIA Assistant",
      "GAIA Personal AI",
      "heygaia",
    ],
    url: siteConfig.url,
    logo: `${siteConfig.url}/images/logos/logo.webp`,
    image: `${siteConfig.url}/og-image.webp`,
    description: siteConfig.description,
    email: SUPPORT_EMAIL,
    sameAs: [
      // External profiles only — the org's own URL lives on the `url` property.
      siteConfig.links.twitter,
      siteConfig.links.github,
      siteConfig.links.linkedin,
      siteConfig.links.youtube,
      siteConfig.links.discord,
      "https://docs.heygaia.io",
    ],
    founders: siteConfig.founders.map(
      (founder): Person => ({
        "@type": "Person",
        name: founder.name,
        jobTitle: founder.role,
        sameAs: [founder.twitter, founder.linkedin].filter(Boolean),
      }),
    ),
    contactPoint: supportContactPoint,
    slogan: "Your Personal AI Assistant",
    keywords: "AI assistant, personal AI, productivity, automation, GAIA",
  };
}

export function generateWebSiteSchema(): WithContext<WebSite> {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: siteConfig.short_name,
    alternateName: siteConfig.name,
    url: siteConfig.url,
    description: siteConfig.description,
  };
}
