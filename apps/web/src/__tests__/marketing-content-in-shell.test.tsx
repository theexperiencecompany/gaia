/** A marketing page is in the HTML shell: React outlines a Suspense boundary over 12.8 KB and reveals it up to 300 ms after first paint, delaying the LCP. */

import { existsSync } from "node:fs";
import path from "node:path";
import { prerender } from "react-dom/static";
import { describe, expect, it, vi } from "vitest";

import LocaleLandingLayout from "@/app/[locale]/(landing)/layout";
import LocaleLayout from "@/app/[locale]/layout";

vi.mock("@/app/fonts", () => ({
  defaultFont: { className: "" },
  getAllFontVariables: () => "",
}));
vi.mock("next-intl/server", () => ({ setRequestLocale: () => undefined }));
vi.mock("@/i18n/navigation", () => ({ usePathname: () => "/pricing" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => undefined }),
  useParams: () => ({ locale: "en" }),
  usePathname: () => "/pricing",
  useSearchParams: () => new URLSearchParams(),
  notFound: () => {
    throw new Error("notFound");
  },
}));

const APP_DIR = path.resolve(__dirname, "../app/[locale]");
const PAGE_MARKER = "marketing-page-marker";
/** Well past React's 12800-byte progressive chunk size, as every marketing page is. */
const PAGE_BYTES = 40_000;

async function renderMarketingPage(): Promise<string> {
  const page = (
    <section id={PAGE_MARKER}>
      <p>{"GAIA ".repeat(PAGE_BYTES / 5)}</p>
    </section>
  );
  const document = await LocaleLayout({
    params: Promise.resolve({ locale: "en" }),
    children: <LocaleLandingLayout>{page}</LocaleLandingLayout>,
  });
  const { prelude } = await prerender(document);
  return new Response(prelude).text();
}

describe("marketing page HTML", () => {
  it("has no loading.tsx above the landing group, which would wrap every page in a Suspense boundary", () => {
    expect(existsSync(path.join(APP_DIR, "loading.tsx"))).toBe(false);
    expect(existsSync(path.join(APP_DIR, "(landing)/loading.tsx"))).toBe(false);
  });

  it("paints the page from the shell, not from a boundary revealed later", async () => {
    const html = await renderMarketingPage();
    const pageAt = html.indexOf(`id="${PAGE_MARKER}"`);
    const firstOutlinedSegment = html.indexOf('<div hidden id="S:');

    expect(pageAt).toBeGreaterThan(-1);
    if (firstOutlinedSegment !== -1) {
      expect(pageAt).toBeLessThan(firstOutlinedSegment);
    }
  });
});
