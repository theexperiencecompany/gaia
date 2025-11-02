import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Request a Feature",
  description:
    "Have an idea to improve GAIA? Request new features, vote on existing suggestions, and help shape the future of GAIA. Your feedback drives our development priorities.",
  path: "/request-feature",
  keywords: [
    "request feature",
    "feature request",
    "suggest feature",
    "product feedback",
    "feature voting",
    "improvement ideas",
    "user feedback",
    "product suggestions",
  ],
});

export default function RequestFeaturePage() {
  redirect("https://gaia.featurebase.app");
}
