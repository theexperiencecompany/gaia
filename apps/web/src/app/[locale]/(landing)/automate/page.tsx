import type { Metadata } from "next";

import { AutomateHub } from "./Hub";
import { automateHubMetadata } from "./metadata";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
  }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  return automateHubMetadata(locale);
}

export default async function AutomateHubPage({ params }: PageProps) {
  const { locale } = await params;
  return <AutomateHub locale={locale} page={1} />;
}
