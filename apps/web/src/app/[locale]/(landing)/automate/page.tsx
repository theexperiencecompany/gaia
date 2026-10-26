import type { Metadata } from "next";
import { AutomateHubPage, generateAutomateHubMetadata } from "./AutomateHub";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
  }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  return generateAutomateHubMetadata(locale, 1);
}

export default async function AutomateHubFirstPage({ params }: PageProps) {
  const { locale } = await params;
  return <AutomateHubPage locale={locale} page={1} />;
}
