import type { Metadata } from "next";
import { FeaturesGrid } from "@/features/landing/components/features/FeaturesGrid";

export const metadata: Metadata = {
  title: "Features",
  description:
    "Everything GAIA can do across AI intelligence, productivity, automation, integrations, and every platform you use.",
};

export default function FeaturesPage() {
  return <FeaturesGrid />;
}
