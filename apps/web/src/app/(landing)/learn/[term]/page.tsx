import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import FinalSection from "@/features/landing/components/sections/FinalSection";
import JsonLd from "@/components/seo/JsonLd";
import {
  getAllGlossaryTermSlugs,
  getGlossaryTerm,
} from "@/features/glossary/data/glossaryData";
import {
  generateBreadcrumbSchema,
  generateDefinedTermSchema,
  generateFAQSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  params: Promise<{ term: string }>;
}

export async function generateStaticParams() {
  return getAllGlossaryTermSlugs().map((term) => ({
    term,
  }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { term } = await params;
  const data = getGlossaryTerm(term);

  if (!data) {
    return { title: "Term Not Found" };
  }

  return generatePageMetadata({
    title: data.metaTitle,
    description: data.metaDescription,
    path: `/learn/${term}`,
    keywords: data.keywords,
  });
}

export default async function GlossaryTermPage({
  params,
}: PageProps) {
  const { term } = await params;
  const data = getGlossaryTerm(term);

  if (!data) {
    notFound();
  }

  const webPageSchema = generateWebPageSchema(
    data.metaTitle,
    data.metaDescription,
    `${siteConfig.url}/learn/${term}`,
    [
      { name: "Home", url: siteConfig.url },
      {
        name: "Glossary",
        url: `${siteConfig.url}/learn`,
      },
      {
        name: data.term,
        url: `${siteConfig.url}/learn/${term}`,
      },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Glossary", url: `${siteConfig.url}/learn` },
    {
      name: data.term,
      url: `${siteConfig.url}/learn/${term}`,
    },
  ]);

  const faqSchema = generateFAQSchema(data.faqs);

  const definedTermSchema = generateDefinedTermSchema(
    data.term,
    data.definition,
    `${siteConfig.url}/learn/${term}`,
  );

  const relatedTerms = data.relatedTerms
    .map((slug) => getGlossaryTerm(slug))
    .filter(
      (t): t is NonNullable<typeof t> => t !== undefined,
    );

  return (
    <>
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          faqSchema,
          definedTermSchema,
        ]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            Home
          </Link>
          <span className="mx-2">/</span>
          <Link
            href="/learn"
            className="hover:text-zinc-300"
          >
            Glossary
          </Link>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">
            {data.term}
          </span>
        </nav>

        {/* Definition Hero */}
        <header className="mb-16">
          <h1 className="mb-6 font-serif text-5xl font-normal text-white md:text-6xl">
            {data.term}
          </h1>
          <div className="rounded-3xl bg-zinc-800 p-8">
            <p className="text-xl leading-relaxed text-zinc-200">
              {data.definition}
            </p>
          </div>
        </header>

        {/* Extended Description */}
        <section className="mb-16">
          <h2 className="mb-4 text-3xl font-semibold text-white">
            Understanding {data.term}
          </h2>
          <p className="text-lg leading-relaxed text-zinc-300">
            {data.extendedDescription}
          </p>
        </section>

        {/* How GAIA Uses It */}
        <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
          <h2 className="mb-4 text-2xl font-semibold text-emerald-400">
            How GAIA Uses {data.term}
          </h2>
          <p className="text-lg leading-relaxed text-zinc-300">
            {data.howGaiaUsesIt}
          </p>
        </section>

        {/* Related Terms */}
        {relatedTerms.length > 0 && (
          <section className="mb-16">
            <h2 className="mb-6 text-3xl font-semibold text-white">
              Related Concepts
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {relatedTerms.map((related) => (
                <Link
                  key={related.slug}
                  href={`/learn/${related.slug}`}
                  className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
                >
                  <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                    {related.term}
                  </h3>
                  <p className="line-clamp-2 text-sm leading-relaxed text-zinc-400">
                    {related.definition}
                  </p>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* FAQ */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Frequently Asked Questions
          </h2>
          <div className="space-y-6">
            {data.faqs.map((faq) => (
              <div
                key={faq.question}
                className="rounded-2xl bg-zinc-800 p-6"
              >
                <h3 className="mb-2 text-lg font-medium text-white">
                  {faq.question}
                </h3>
                <p className="leading-relaxed text-zinc-400">
                  {faq.answer}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Explore More */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Explore More
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Link
              href="/compare"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                Compare GAIA with Alternatives
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                See how GAIA stacks up against other AI productivity
                tools in detailed comparisons.
              </p>
            </Link>
            <Link
              href="/for"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                GAIA for Your Role
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Discover how GAIA helps professionals in different
                roles work smarter with AI.
              </p>
            </Link>
          </div>
        </section>

      </article>

      <FinalSection />
    </>
  );
}
