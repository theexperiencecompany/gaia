import type { Metadata } from "next";
import type { Offer, SoftwareApplication, WithContext } from "schema-dts";
import JsonLd from "@/components/seo/JsonLd";
import { DownloadPage } from "@/features/download";
import { GITHUB_RELEASES_BASE } from "@/hooks/ui/usePlatformDetection";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Download",
  description:
    "Download GAIA for your desktop. Available for macOS (Intel & Apple Silicon), Windows, and Linux. Get the desktop app with enhanced performance and system integration.",
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
    offers: {
      "@type": "Offer",
      price: "0",
      priceCurrency: "USD",
      availability: "https://schema.org/InStock",
    } as Offer,
    downloadUrl: GITHUB_RELEASES_BASE,
    softwareVersion: "Latest",
    releaseNotes: `${siteConfig.url}/download`,
    author: {
      "@type": "Organization",
      name: siteConfig.short_name,
      url: siteConfig.url,
    },
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
