import type { Metadata } from "next";
import { generatePageMetadata } from "@/lib/seo";
import FoundersClient from "./FoundersClient";

export const metadata: Metadata = generatePageMetadata({
  title: "GAIA for Startup Founders — Your AI Chief of Staff",
  description:
    "GAIA handles your inbox, automates your workflows, preps your meetings, and drafts investor updates — so you can focus on building.",
  path: "/founders",
  keywords: [
    "AI for founders",
    "startup AI assistant",
    "AI chief of staff",
    "founder productivity",
    "investor update automation",
    "workflow automation for startups",
  ],
});

export default function FoundersPage() {
  return <FoundersClient />;
}
