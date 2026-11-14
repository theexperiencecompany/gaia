/** /signup is indexed and in the sitemap while every hosted sign-up CTA goes straight to WorkOS, so the footer is its inbound link. */
import { describe, expect, it } from "vitest";

import { footerSections } from "@/config/appConfig";
import { siteConfig } from "@/lib/seo";
import { getSitemapEntries, SITEMAP_IDS } from "@/lib/sitemapData";

const SIGNUP_PATH = "/signup";

describe("footer sign-up link", () => {
  it("links the indexed sign-up page from the footer", async () => {
    const sitemap = (await getSitemapEntries(SITEMAP_IDS.STATIC)).map(
      (entry) => entry.url,
    );
    expect(sitemap).toContain(`${siteConfig.url}${SIGNUP_PATH}`);

    const footerHrefs = footerSections.flatMap((section) =>
      section.links.map((link) => link.href),
    );
    expect(footerHrefs).toContain(SIGNUP_PATH);
  });
});
