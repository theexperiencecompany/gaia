"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  CreditBalance,
  CreditPack,
} from "@/features/settings/api/usageApi";
import UsageSettings from "@/features/settings/components/UsageSettings";

const inDays = (n: number) =>
  new Date(Date.now() + n * 86_400_000).toISOString();

const balance: CreditBalance = {
  plan_type: "pro",
  allotment_remaining: 158_420,
  topup_remaining: 42_300,
  total_remaining: 200_720,
  periods: {
    day: {
      used: 2_100,
      limit: 15_000,
      remaining: 12_900,
      reset_time: inDays(1),
      breakdown: [
        { key: "chat", title: "Chat", credits: 1_400 },
        { key: "web_search", title: "Web search", credits: 500 },
        { key: "image_generation", title: "Image generation", credits: 200 },
      ],
    },
    month: {
      used: 41_580,
      limit: 200_000,
      remaining: 158_420,
      reset_time: inDays(12),
      breakdown: [
        { key: "chat", title: "Chat", credits: 28_400 },
        { key: "deep_research", title: "Deep research", credits: 8_000 },
        { key: "web_search", title: "Web search", credits: 3_180 },
        { key: "image_generation", title: "Image generation", credits: 2_000 },
      ],
    },
  },
  topup_grants: [{ remaining: 42_300, expires_at: inDays(330) }],
};

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

const feature = (
  title: string,
  description: string,
  used: number,
  dayLimit: number,
  monthLimit: number,
) => ({
  title,
  description,
  periods: {
    day: {
      used,
      limit: dayLimit,
      percentage: Math.min(100, (used / dayLimit) * 100),
      reset_time: inDays(1),
      remaining: Math.max(0, dayLimit - used),
    },
    month: {
      used,
      limit: monthLimit,
      percentage: Math.min(100, (used / monthLimit) * 100),
      reset_time: inDays(12),
      remaining: Math.max(0, monthLimit - used),
    },
  },
});

const summary = {
  user_id: "preview",
  plan_type: "pro",
  features: {
    generate_image: feature(
      "AI Image Generation",
      "Generate images using AI models",
      12,
      45,
      1350,
    ),
    deep_research: feature(
      "Deep Research",
      "Multi-source research with full content analysis",
      4,
      20,
      600,
    ),
    web_search: feature(
      "Web Search",
      "Search the web for information",
      88,
      450,
      13500,
    ),
  },
  last_updated: new Date().toISOString(),
};

export default function CreditsPreviewPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(["creditBalance"], balance);
  client.setQueryData(["creditPacks"], packs);
  client.setQueryData(["usageSummary"], summary);

  return (
    <QueryClientProvider client={client}>
      <div className="min-h-screen bg-[#111111] py-12">
        <div className="mx-auto max-w-2xl px-4">
          <h1 className="mb-6 text-lg font-medium text-white">
            Usage & Credits
          </h1>
          <UsageSettings />
        </div>
      </div>
    </QueryClientProvider>
  );
}
