import type { Metadata } from "next";
import { generatePageMetadata } from "@/lib/seo";
import { IntegrationsPageClient } from "./client";

export const metadata: Metadata = generatePageMetadata({
  title: "Integration Marketplace",
  description:
    "Discover and clone MCP integrations built by the community. Connect AI tools to your favorite services.",
  path: "/marketplace",
  keywords: [
    "MCP integrations",
    "AI integrations",
    "community integrations",
    "MCP servers",
    "AI tools",
    "GAIA integrations",
    "integration marketplace",
  ],
});

export default function MarketplacePage() {
  return <IntegrationsPageClient />;
}
