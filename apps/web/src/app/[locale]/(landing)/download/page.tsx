import type { Metadata } from "next";
import type { SoftwareApplication, WithContext } from "schema-dts";
import JsonLd from "@/components/seo/JsonLd";
import DownloadPage from "@/features/download/components/DownloadPage";
import { GITHUB_RELEASES_BASE } from "@/hooks/ui/usePlatformDetection";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateProOffer,
  generateWebPageSchema,
  organizationRef,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Download GAIA: Desktop App for Mac, Windows, and Linux",
  description:
    "Get the GAIA desktop app for macOS (Intel and Apple Silicon), Windows, and Linux: your AI assistant for email, calendar, and tasks, one shortcut away.",
  path: "/download",
  keywords: [
    "GAIA Download",
    "Desktop App",
    "macOS App",
    "Windows App",
    "Linux App",
    "AI Assistant Desktop",
    "Native App",
    "Download GAIA",
    "Apple Silicon",
    "M1",
    "M2",
    "M3",
    "Intel Mac",
    "Windows Download",
    "Linux Download",
    "Desktop Application",
  ],
});

function generateDownloadSchema(): WithContext<SoftwareApplication> {
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "GAIA",
    applicationCategory: "ProductivityApplication",
    operatingSystem: "Windows, macOS, Linux",
    description:
      "GAIA is your personal AI assistant to proactively manage your email, calendar, todos, workflows and all your digital tools to boost productivity.",
    offers: generateProOffer(),
    downloadUrl: GITHUB_RELEASES_BASE,
    softwareVersion: "Latest",
    releaseNotes: `${siteConfig.url}/download`,
    author: organizationRef,
    screenshot: `${siteConfig.url}/images/screenshots/desktop_dock.png`,
  };
}

export default function Download() {
  const webPageSchema = generateWebPageSchema(
    "Download GAIA",
    "Download GAIA for macOS, Windows, and Linux. Experience GAIA on desktop.",
    `${siteConfig.url}/download`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Download", url: `${siteConfig.url}/download` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Download", url: `${siteConfig.url}/download` },
  ]);
  const downloadSchema = generateDownloadSchema();

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, downloadSchema]} />
      <DownloadPage />
    </>
  );
}
