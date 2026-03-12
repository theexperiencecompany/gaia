import type { Metadata } from "next";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Use Cases",
  description:
    "Discover practical use cases and workflows for GAIA. Learn how to automate tasks, manage emails, schedule meetings, track goals, and boost productivity with AI-powered workflows.",
  path: "/use-cases",
  keywords: [
    "GAIA Use Cases",
    "AI Workflows",
    "Automation Examples",
    "Productivity Workflows",
    "AI Use Cases",
    "Task Automation",
    "Workflow Templates",
    "AI Productivity",
  ],
});

export default function UseCasesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
