import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import { hubPageCount } from "@/lib/hubPagination";

import { LearnHub } from "../../Hub";
import { glossaryHubMetadata } from "../../metadata";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly page: string;
  }>;
}

export async function generateStaticParams() {
  const terms = await getAllGlossaryTerms();
  return Array.from({ length: hubPageCount(terms.length) - 1 }, (_, index) => ({
    page: String(index + 2),
  }));
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  return glossaryHubMetadata(locale);
}

export default async function LearnHubPage({ params }: PageProps) {
  const { locale, page } = await params;
  const pageNumber = Number.parseInt(page, 10);
  const terms = await getAllGlossaryTerms();
  if (!/^\d+$/.test(page) || pageNumber < 2) notFound();
  if (pageNumber > hubPageCount(terms.length)) notFound();
  return <LearnHub locale={locale} page={pageNumber} />;
}
