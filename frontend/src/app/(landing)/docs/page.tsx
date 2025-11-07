import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Documentation",
  description:
    "Comprehensive documentation for GAIA. Learn how to set up, configure, and use GAIA to its full potential. Find guides, tutorials, API references, and best practices.",
  path: "/docs",
  keywords: [
    "GAIA documentation",
    "docs",
    "user guide",
    "setup guide",
    "tutorials",
    "API documentation",
    "how-to guides",
    "technical documentation",
  ],
});

export default function DocsPage() {
  redirect("https://docs.heygaia.io");
}
