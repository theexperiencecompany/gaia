import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import { hubPageCount } from "@/lib/hubPagination";

import { ComparisonsHub } from "../../Hub";
import { comparisonsHubMetadata } from "../../metadata";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly page: string;
  }>;
}

export async function generateStaticParams() {
  const comparisons = await getAllComparisons();
  return Array.from(
    { length: hubPageCount(comparisons.length) - 1 },
    (_, index) => ({ page: String(index + 2) }),
  );
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  return comparisonsHubMetadata(locale);
}

export default async function ComparisonsHubPage({ params }: PageProps) {
  const { locale, page } = await params;
  const pageNumber = Number.parseInt(page, 10);
  const comparisons = await getAllComparisons();
  if (!/^\d+$/.test(page) || pageNumber < 2) notFound();
  if (pageNumber > hubPageCount(comparisons.length)) notFound();
  return <ComparisonsHub locale={locale} page={pageNumber} />;
}
