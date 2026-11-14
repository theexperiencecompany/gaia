// @vitest-environment jsdom
// Regression: each page's above-the-fold LCP image loads eagerly at high fetch
// priority; lazy loading held /blog/[slug] and /download's LCP back ~6 s on mobile.
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import BlogPostClient from "@/app/[locale]/(landing)/blog/client";
import DownloadPage from "@/features/download/components/DownloadPage";
import type { BlogContentPost } from "@/lib/blog";

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/features/landing/components/sections/FinalSection", () => ({
  default: () => null,
}));
vi.mock("@/hooks/ui/usePlatformDetection", () => ({
  GITHUB_RELEASES_BASE: "https://github.com/theexperiencecompany/gaia/releases",
  usePlatformDetection: () => ({
    detectedDesktop: null,
    isDesktopReleaseLoading: false,
    desktopDownloads: { mac: [], windows: [], linux: [] },
  }),
}));

const POST: BlogContentPost = {
  slug: "why-open-source",
  title: "Why open source",
  description: "Why GAIA is open source.",
  date: "2026-01-01",
  category: "Company",
  image: "/images/blog/open-source.webp",
  authors: [],
  content: "Body.",
};

function expectEagerHighPriority(image: HTMLElement) {
  expect(image.getAttribute("loading")).not.toBe("lazy");
  expect(image.getAttribute("fetchpriority")).toBe("high");
}

describe("marketing LCP images", () => {
  it("loads the blog post hero eagerly, sized to its column", () => {
    render(
      <NextIntlClientProvider locale="en" messages={{}}>
        <BlogPostClient
          blog={POST}
          suggestedPosts={[]}
          structuredData={{
            "@context": "https://schema.org",
            "@type": "Article",
          }}
          breadcrumbSchema={{
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
          }}
        />
      </NextIntlClientProvider>,
    );
    const hero = screen.getByAltText(POST.title);

    expectEagerHighPriority(hero);
    expect(hero.getAttribute("sizes")).toBe("(max-width: 768px) 100vw, 728px");
  });

  it("loads the download page's desktop screenshot eagerly", () => {
    render(<DownloadPage />);

    expectEagerHighPriority(screen.getByAltText("GAIA Desktop App webp"));
  });
});
