import type { Metadata } from "next";
import { CompareHubPage, generateCompareHubMetadata } from "./CompareHub";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
  }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  return generateCompareHubMetadata(locale, 1);
}

export default async function ComparisonsHubPage({ params }: PageProps) {
  const { locale } = await params;
  return <CompareHubPage locale={locale} page={1} />;
}
