import type { Metadata } from "next";
import { generateLearnHubMetadata, LearnHubPage } from "./LearnHub";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
  }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  return generateLearnHubMetadata(locale, 1);
}

export default async function LearnHubFirstPage({ params }: PageProps) {
  const { locale } = await params;
  return <LearnHubPage locale={locale} page={1} />;
}
