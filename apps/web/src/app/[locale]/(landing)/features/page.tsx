import type { Metadata } from "next";
import { FeaturesGrid } from "@/features/landing/components/features/FeaturesGrid";
import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Features",
  description:
    "Everything GAIA can do across AI intelligence, productivity, automation, integrations, and every platform you use.",
  path: "/features",
});

export default function FeaturesPage() {
  return <FeaturesGrid />;
}
