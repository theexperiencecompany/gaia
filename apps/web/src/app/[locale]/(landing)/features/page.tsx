import type { Metadata } from "next";
import { FeaturesGrid } from "@/features/landing/components/features/FeaturesGrid";

export const metadata: Metadata = {
  title: "Features — GAIA",
  description:
    "Everything GAIA can do. 30 capabilities across AI intelligence, productivity, automation, integrations, and multi-platform.",
};

export default function FeaturesPage() {
  return <FeaturesGrid />;
}
