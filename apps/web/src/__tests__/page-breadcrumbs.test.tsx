// @vitest-environment jsdom
import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PageBreadcrumbs } from "@/components/seo/PageBreadcrumbs";

const CRUMBS = [
  { label: "Home", href: "/" },
  { label: "Comparisons", href: "/compare" },
  { label: "GAIA vs Notion" },
];

const render = (locale: string): Document => {
  const html = renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={{}}>
      <PageBreadcrumbs items={CRUMBS} />
    </NextIntlClientProvider>,
  );
  return new DOMParser().parseFromString(html, "text/html");
};

describe("PageBreadcrumbs", () => {
  it("renders a labelled nav with an ordered list of every crumb", () => {
    const doc = render("en");
    const nav = doc.querySelector("nav");
    expect(nav?.getAttribute("aria-label")).toBeTruthy();
    const items = [...doc.querySelectorAll("nav ol > li")];
    expect(items.map((li) => li.textContent?.trim())).toEqual([
      "Home",
      "Comparisons",
      "GAIA vs Notion",
    ]);
  });

  it("marks only the last crumb as the current page, and does not link it", () => {
    const doc = render("en");
    const current = [...doc.querySelectorAll('[aria-current="page"]')];
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toBe("GAIA vs Notion");
    expect(current[0].closest("a")).toBeNull();
  });

  it("underlines every link so it is distinguishable without color", () => {
    const links = [...render("en").querySelectorAll("nav a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/", "/compare"]);
    for (const link of links) {
      expect(link.className).toMatch(/(^|\s|:)underline(\s|$)/);
      // squirrel's link-in-text-block flags any class containing this substring
      expect(link.className).not.toMatch(/no-underline/);
    }
  });

  it("keeps the visitor's locale only on translated route families", () => {
    const hrefs = [...render("fr").querySelectorAll("nav a")].map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toEqual(["/", "/fr/compare"]);
  });
});
