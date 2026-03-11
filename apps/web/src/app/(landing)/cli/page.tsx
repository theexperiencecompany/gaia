import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { InstallPageClient } from "./InstallPageClient";

export const metadata: Metadata = generatePageMetadata({
  title: "Install GAIA CLI",
  description:
    "Install the GAIA CLI tool to quickly set up and manage your self-hosted GAIA instance. One command to get started with your AI assistant.",
  path: "/install",
  keywords: [
    "GAIA CLI",
    "Install GAIA",
    "Self-hosted Setup",
    "Command Line",
    "CLI Tool",
    "Quick Install",
    "GAIA Setup",
    "Developer Tools",
  ],
});

export default function InstallPage() {
  const webPageSchema = generateWebPageSchema(
    "Install GAIA CLI",
    "Quick installation guide for the GAIA CLI tool",
    `${siteConfig.url}/install`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Install", url: `${siteConfig.url}/install` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Install", url: `${siteConfig.url}/install` },
  ]);

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema]} />
      <InstallPageClient />
    </>
  );
}
