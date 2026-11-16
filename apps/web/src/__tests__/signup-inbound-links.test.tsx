// @vitest-environment jsdom
/** /signup is indexed while every hosted sign-up CTA goes straight to WorkOS, so the footer and the download page's web section link it. */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { footerSections } from "@/config/appConfig";
import DownloadPage from "@/features/download/components/DownloadPage";
import { siteConfig } from "@/lib/seo";
import { getSitemapEntries, SITEMAP_IDS } from "@/lib/sitemapData";

vi.mock("next/image", () => ({ default: () => null }));

const SIGNUP_PATH = "/signup";

describe("sign-up page inbound links", () => {
  it("lists /signup in the sitemap and links it from the footer", async () => {
    const sitemap = (await getSitemapEntries(SITEMAP_IDS.STATIC)).map(
      (entry) => entry.url,
    );
    expect(sitemap).toContain(`${siteConfig.url}${SIGNUP_PATH}`);
    const footerHrefs = footerSections.flatMap((section) =>
      section.links.map((link) => link.href),
    );
    expect(footerHrefs).toContain(SIGNUP_PATH);
  });

  it("links /signup from the download page's body", () => {
    const doc = new DOMParser().parseFromString(
      renderToStaticMarkup(<DownloadPage />),
      "text/html",
    );
    expect(doc.querySelector(`a[href="${SIGNUP_PATH}"]`)).not.toBeNull();
  });
});
