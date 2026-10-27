import type { Metadata } from "next";

import { LearnHub } from "./Hub";
import { glossaryHubMetadata } from "./metadata";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
  }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  return glossaryHubMetadata(locale);
}

export default async function LearnHubPage({ params }: PageProps) {
  const { locale } = await params;
  return <LearnHub locale={locale} page={1} />;
}
