import type { Metadata } from "next";
import { getGuide } from "@/features/guides/data/guidesData";
import { generatePageMetadata } from "@/lib/seo";

export async function generateGuideMetadata(slug: string): Promise<Metadata> {
  const guide = await getGuide(slug);
  return generatePageMetadata({
    title: guide.metaTitle,
    description: guide.metaDescription,
    path: `/${guide.slug}`,
    keywords: [...guide.keywords],
  });
}
