import type { Metadata } from "next";

import ShortLinkResolver from "@/features/short-links/components/ShortLinkResolver";

export const metadata: Metadata = {
  title: "Opening link",
};

interface PageProps {
  params: Promise<{ slug: string }>;
}

export default async function ShortLinkPage({ params }: PageProps) {
  const { slug } = await params;
  return <ShortLinkResolver slug={slug} />;
}
