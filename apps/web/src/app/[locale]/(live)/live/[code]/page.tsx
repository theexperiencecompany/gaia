import { LiveViewPage } from "@/features/chat/components/browser/LiveViewPage";

interface LivePageProps {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ t?: string | string[] }>;
}

export default async function LivePage({
  params,
  searchParams,
}: LivePageProps) {
  const { code } = await params;
  const { t } = await searchParams;
  return <LiveViewPage code={code} token={typeof t === "string" ? t : null} />;
}
