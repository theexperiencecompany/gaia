// @vitest-environment jsdom
/**
 * The server-rendered markup crawlers and assistive tech read: one main
 * landmark, a skip link to it, no skipped heading levels, valid lists, and
 * icon links whose accessible name contains their visible text (WCAG 2.5.3).
 */
import { globSync, readFileSync } from "node:fs";
import path from "node:path";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement, ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import InboxZeroAiClient from "@/app/[locale]/(landing)/inbox-zero-ai/InboxZeroAiClient";
import UseCaseDetailClient from "@/app/[locale]/(landing)/use-cases/[slug]/client";
import LandingLayoutShell from "@/components/layouts/LandingLayoutShell";
import Footer from "@/components/navigation/Footer";
import { BlogList } from "@/features/blog/components/BlogList";
import ContactSidebar from "@/features/contact/components/ContactSidebar";
import type { BlogPostMeta } from "@/lib/blog";
import type { UseCase } from "@/types/features/workflowTypes";

vi.mock("next/image", () => ({ default: () => null }));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/navigation/Navbar", () => ({
  default: () => (
    <nav>
      <a href="/pricing">Pricing</a>
    </nav>
  ),
}));

vi.mock("@/layouts/LandingProvidersLayout", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/features/landing/components/sections/FinalSection", () => ({
  default: () => null,
}));

vi.mock("@/features/landing/components/sections/PersonaSEOSection", () => ({
  default: () => null,
}));

vi.mock("@/features/use-cases/components/YouMightAlsoLike", () => ({
  default: () => null,
}));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));

vi.mock("@/features/chat/hooks/useWorkflowSelection", () => ({
  useWorkflowSelection: () => ({ selectWorkflow: vi.fn() }),
}));

vi.mock("@/features/workflows/hooks/useWorkflowCreation", () => ({
  useWorkflowCreation: () => ({ createWorkflow: vi.fn() }),
}));

vi.mock("@/features/integrations/hooks/useIntegrations", () => ({
  useIntegrations: () => ({ integrations: [] }),
}));

vi.mock("@/features/integrations/hooks/useIntegrationLookup", () => ({
  useIntegrationLookup: () => ({
    getIntegrationName: () => undefined,
    getIntegrationIconUrl: () => undefined,
  }),
}));

function parse(element: ReactElement): Document {
  return new DOMParser().parseFromString(
    renderToStaticMarkup(
      <NextIntlClientProvider locale="en" messages={{}}>
        {element}
      </NextIntlClientProvider>,
    ),
    "text/html",
  );
}

/** Each heading that goes more than one level deeper than the one before it. */
function headingSkips(doc: Document): string[] {
  const levels = [...doc.querySelectorAll("h1, h2, h3, h4, h5, h6")].map(
    (heading) => Number(heading.tagName.slice(1)),
  );
  return levels.flatMap((level, index) =>
    index > 0 && level > levels[index - 1] + 1
      ? [`H${levels[index - 1]} -> H${level}`]
      : [],
  );
}

const normalize = (text: string | null) =>
  (text ?? "").replace(/\s+/g, " ").trim().toLowerCase();

/** Links whose aria-label does not contain the text a sighted user perceives. */
function nameMismatches(doc: Document): string[] {
  return [...doc.querySelectorAll("a[aria-label]")].flatMap((link) => {
    const visible = normalize(link.textContent);
    const name = normalize(link.getAttribute("aria-label"));
    return visible && !name.includes(visible)
      ? [`"${visible}" vs aria-label "${name}"`]
      : [];
  });
}

const AUTHOR = { name: "Aryan", role: "Founder", avatar: "/a.png" };

const blog = (slug: string, featured: boolean): BlogPostMeta => ({
  slug,
  title: `Post ${slug}`,
  date: "2026-01-01",
  authors: [AUTHOR],
  category: "Engineering",
  image: "/b.png",
  featured,
});

const USE_CASE: UseCase = {
  title: "Morning briefing",
  description: "A summary of your day",
  action_type: "workflow",
  integrations: ["gmail"],
  categories: ["productivity"],
  published_id: "wf_1",
  slug: "morning-briefing",
  steps: [
    { id: "s1", title: "Read inbox", description: "Scan", category: "gmail" },
    { id: "s2", title: "Summarize", description: "Write", category: "gmail" },
  ],
};

describe("landing markup accessibility", () => {
  it("names every footer and contact social link with its visible text", () => {
    expect(nameMismatches(parse(<Footer />))).toEqual([]);
    expect(nameMismatches(parse(<ContactSidebar />))).toEqual([]);
  });

  it("gives the landing shell one main, reached by a leading skip link", () => {
    const doc = parse(
      <LandingLayoutShell selfhost={false}>
        <h1>Page</h1>
      </LandingLayoutShell>,
    );

    const mains = doc.querySelectorAll("main");
    expect(mains).toHaveLength(1);

    const firstLink = doc.querySelector("a");
    expect(firstLink?.getAttribute("href")).toBe(`#${mains[0].id}`);
    expect(mains[0].id).not.toBe("");
  });

  it("renders no main of its own on any page, since the layout shell owns it", () => {
    const appDir = path.resolve(__dirname, "../app");
    const pagesWithMain = globSync("**/*.tsx", { cwd: appDir }).filter(
      (file) =>
        !file.endsWith("layout.tsx") &&
        /<main\b/.test(readFileSync(path.join(appDir, file), "utf8")),
    );
    expect(pagesWithMain).toEqual(["[locale]/file-icons/page.tsx"]);
  });

  it("keeps the app layout to a single main", () => {
    const layout = readFileSync(
      path.resolve(__dirname, "../components/layouts/MainLayoutShell.tsx"),
      "utf8",
    );
    expect(layout).toContain("<SidebarInset");
    expect(layout).not.toMatch(/<main\b/);
  });

  it("does not skip heading levels under the contact page h1", () => {
    const doc = parse(
      <>
        <h1>Contact us</h1>
        <ContactSidebar />
        <h2>Send us a message</h2>
      </>,
    );
    expect(headingSkips(doc)).toEqual([]);
  });

  it("does not skip heading levels under the blog index h1", () => {
    const doc = parse(
      <>
        <h1>Blog</h1>
        <BlogList blogs={[blog("a", true), blog("b", false)]} />
      </>,
    );
    expect(doc.querySelectorAll("h2")).toHaveLength(2);
    expect(headingSkips(doc)).toEqual([]);
  });

  it("does not skip heading levels on a use-case page", () => {
    const doc = parse(
      <UseCaseDetailClient
        useCase={USE_CASE}
        communityWorkflow={null}
        slug="morning-briefing"
      />,
    );
    expect(doc.querySelector("h1")?.textContent).toBe("Morning briefing");
    expect(headingSkips(doc)).toEqual([]);
  });

  it("gives every list on the inbox-zero page only li children", () => {
    const doc = parse(<InboxZeroAiClient />);
    const invalid = [...doc.querySelectorAll("ol, ul")].flatMap((list) =>
      [...list.children]
        .filter((child) => child.tagName !== "LI")
        .map((child) => `${list.tagName} > ${child.tagName}`),
    );
    expect(invalid).toEqual([]);
  });
});
