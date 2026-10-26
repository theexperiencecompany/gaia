import type { Metadata } from "next";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { comboHubPages } from "@/features/integrations/lib/comboHubPages";
import { laterHubPageParams } from "@/lib/hubPagination";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import {
  AutomateHubPage,
  generateAutomateHubMetadata,
} from "../../AutomateHub";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly page: string;
  }>;
}

export function generateStaticParams() {
  return prerenderedMarketingParams(async () =>
    laterHubPageParams(comboHubPages(await getAllCombos())),
  );
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale, page } = await params;
  return generateAutomateHubMetadata(locale, Number(page));
}

export default async function AutomateHubLaterPage({ params }: PageProps) {
  const { locale, page } = await params;
  return <AutomateHubPage locale={locale} page={Number(page)} />;
}
