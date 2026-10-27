import type { ReactNode } from "react";
import JsonLd from "@/components/seo/JsonLd";
import { PageBreadcrumbs } from "@/components/seo/PageBreadcrumbs";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface CategoryHubPageProps {
  readonly title: string;
  /** Breadcrumb text when it differs from the H1 (the comparisons hub uses the longer title). */
  readonly breadcrumbLabel: string;
  readonly subtitle: string;
  readonly pageUrl: string;
  readonly homeLabel: string;
  readonly hubLabel: string;
  readonly hubHref: string;
  readonly categoryLabel: string;
  readonly items: readonly { readonly name: string; readonly url: string }[];
  readonly children: ReactNode;
}

/** Shared chrome for a category page on the comparisons and glossary hubs. */
export function CategoryHubPage({
  title,
  breadcrumbLabel,
  subtitle,
  pageUrl,
  homeLabel,
  hubLabel,
  hubHref,
  categoryLabel,
  items,
  children,
}: CategoryHubPageProps) {
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: hubLabel, url: `${siteConfig.url}${hubHref}` },
    { name: breadcrumbLabel, url: pageUrl },
  ];

  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(title, subtitle, pageUrl, breadcrumbs),
          generateBreadcrumbSchema(breadcrumbs),
          generateItemListSchema(items),
        ]}
      />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <PageBreadcrumbs
          className="mb-8"
          items={[
            { label: homeLabel, href: "/" },
            { label: hubLabel, href: hubHref },
            { label: categoryLabel },
          ]}
        />
        <header className="mb-16">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            {title}
          </h1>
          <p className="max-w-2xl text-xl text-zinc-400">{subtitle}</p>
        </header>

        {children}
      </div>

      <FinalSection />
    </>
  );
}
