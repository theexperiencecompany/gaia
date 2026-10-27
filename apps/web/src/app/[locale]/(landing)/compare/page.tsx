import type { Metadata } from "next";

import { ComparisonsHub } from "./Hub";
import { comparisonsHubMetadata } from "./metadata";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
  }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  return comparisonsHubMetadata(locale);
}

export default async function ComparisonsHubPage({ params }: PageProps) {
  const { locale } = await params;
  return <ComparisonsHub locale={locale} page={1} />;
}
