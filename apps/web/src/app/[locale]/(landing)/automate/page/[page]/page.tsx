import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { hubPageCount } from "@/lib/hubPagination";

import { AutomateHub, automateHubMetadata } from "../../Hub";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly page: string;
  }>;
}

export async function generateStaticParams() {
  const combos = await getAllCombos();
  return Array.from(
    { length: hubPageCount(combos.length) - 1 },
    (_, index) => ({
      page: String(index + 2),
    }),
  );
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  return automateHubMetadata(locale);
}

export default async function AutomateHubPage({ params }: PageProps) {
  const { locale, page } = await params;
  const pageNumber = Number.parseInt(page, 10);
  const combos = await getAllCombos();
  if (!/^\d+$/.test(page) || pageNumber < 2) notFound();
  if (pageNumber > hubPageCount(combos.length)) notFound();
  return <AutomateHub locale={locale} page={pageNumber} />;
}
