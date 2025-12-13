import type { Metadata } from "next";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Blog",
  description:
    "Explore the latest insights, updates, and AI productivity tips from GAIA. Learn about AI automation, productivity hacks, feature announcements, and industry trends.",
  path: "/blog",
  keywords: [
    "GAIA Blog",
    "AI Blog",
    "Productivity Tips",
    "AI Automation",
    "Tech Blog",
    "AI Assistant Updates",
    "Productivity Blog",
  ],
});

export default function BlogLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
