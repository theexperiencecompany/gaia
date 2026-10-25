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
  title: "Install GAIA",
  description:
    "Self-host GAIA with one command: the installer sets up the GAIA CLI, then downloads GAIA and starts it. Keep it running with gaia status, doctor, update and backup.",
  path: "/cli",
  keywords: [
    "GAIA CLI",
    "Install GAIA",
    "Self-host GAIA",
    "Self-hosted AI assistant",
    "GAIA installer",
    "gaia up",
    "Docker",
    "Command Line",
  ],
});

export default function InstallPage() {
  const webPageSchema = generateWebPageSchema(
    "Install GAIA",
    "Self-host GAIA with one command, then manage it with the GAIA CLI",
    `${siteConfig.url}/cli`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Install", url: `${siteConfig.url}/cli` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Install", url: `${siteConfig.url}/cli` },
  ]);

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema]} />
      <InstallPageClient />
    </>
  );
}
