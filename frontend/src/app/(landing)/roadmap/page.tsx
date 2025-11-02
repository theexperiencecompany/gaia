import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Product Roadmap",
  description:
    "Explore GAIA's product roadmap to see upcoming features, planned improvements, and our vision for the future. Vote on features you'd like to see and track development progress.",
  path: "/roadmap",
  keywords: [
    "GAIA roadmap",
    "product roadmap",
    "upcoming features",
    "future updates",
    "development plans",
    "feature requests",
    "product vision",
    "release schedule",
  ],
});

export default function RoadmapPage() {
  redirect("https://gaia.featurebase.app/roadmap");
}
