"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { CreditPack } from "@/features/settings/api/usageApi";
import { TopUpModal } from "@/features/settings/components/TopUpModal";

const packs: CreditPack[] = [
  { key: "small", credits: 50_000, price_cents: 1000, name: "50,000 credits" },
  {
    key: "medium",
    credits: 150_000,
    price_cents: 2800,
    name: "150,000 credits",
  },
  {
    key: "large",
    credits: 500_000,
    price_cents: 8500,
    name: "500,000 credits",
  },
];

export default function CreditsTopUpPreviewPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(["creditPacks"], packs);

  return (
    <QueryClientProvider client={client}>
      <div className="min-h-screen bg-[#111111]" />
      <TopUpModal isOpen onClose={() => {}} />
    </QueryClientProvider>
  );
}
