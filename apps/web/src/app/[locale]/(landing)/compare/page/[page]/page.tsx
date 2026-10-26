import type { Metadata } from "next";
import { comparisonHubPages } from "@/features/comparisons/data/comparisonHubPages";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import { laterHubPageParams } from "@/lib/hubPagination";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import { CompareHubPage, generateCompareHubMetadata } from "../../CompareHub";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly page: string;
  }>;
}

export function generateStaticParams() {
  return prerenderedMarketingParams(async () =>
    laterHubPageParams(comparisonHubPages(await getAllComparisons())),
  );
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale, page } = await params;
  return generateCompareHubMetadata(locale, Number(page));
}

export default async function ComparisonsHubLaterPage({ params }: PageProps) {
  const { locale, page } = await params;
  return <CompareHubPage locale={locale} page={Number(page)} />;
}
