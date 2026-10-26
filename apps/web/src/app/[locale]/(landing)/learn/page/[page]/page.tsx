import type { Metadata } from "next";
import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import { glossaryHubPages } from "@/features/glossary/data/glossaryHubPages";
import { laterHubPageParams } from "@/lib/hubPagination";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import { generateLearnHubMetadata, LearnHubPage } from "../../LearnHub";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly page: string;
  }>;
}

export function generateStaticParams() {
  // Labels do not change how terms page, so the category key stands in for them.
  return prerenderedMarketingParams(async () =>
    laterHubPageParams(
      glossaryHubPages(await getAllGlossaryTerms(), (labelKey) => labelKey),
    ),
  );
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale, page } = await params;
  return generateLearnHubMetadata(locale, Number(page));
}

export default async function LearnHubLaterPage({ params }: PageProps) {
  const { locale, page } = await params;
  return <LearnHubPage locale={locale} page={Number(page)} />;
}
