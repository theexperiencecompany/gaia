import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { TermsIntro } from "./components/TermsIntro";
import { TermsSection18 } from "./components/TermsSection18";
import { TermsSections1To3 } from "./components/TermsSections1To3";
import { TermsSections4And5 } from "./components/TermsSections4And5";
import { TermsSections6To8 } from "./components/TermsSections6To8";
import { TermsSections9To12 } from "./components/TermsSections9To12";
import { TermsSections13To17 } from "./components/TermsSections13To17";
import { TermsSections19And20 } from "./components/TermsSections19And20";

export const metadata: Metadata = generatePageMetadata({
  title: "Terms of Service",
  description:
    "Review GAIA's Terms of Service to understand your rights, responsibilities, and the terms governing your use of our AI assistant platform and services.",
  path: "/terms",
  keywords: [
    "Terms of Service",
    "User Agreement",
    "Service Terms",
    "Legal Policy",
    "Terms and Conditions",
    "Usage Terms",
  ],
});

const TermsOfService = () => {
  const termsSchema = generateWebPageSchema(
    "Terms of Service",
    "Review GAIA's Terms of Service to understand your rights, responsibilities, and the terms governing your use of our AI assistant platform.",
    `${siteConfig.url}/terms`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Terms of Service", url: `${siteConfig.url}/terms` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Terms of Service", url: `${siteConfig.url}/terms` },
  ]);

  return (
    <>
      <JsonLd data={[termsSchema, breadcrumbSchema]} />
      <div className="flex w-full flex-col items-center justify-center">
        <div className="privacy-policy w-full max-w-(--breakpoint-xl) px-4 pb-6 pt-24 sm:px-6 lg:px-8">
          <TermsIntro />
          <TermsSections1To3 />
          <TermsSections4And5 />
          <TermsSections6To8 />
          <TermsSections9To12 />
          <TermsSections13To17 />
          <TermsSection18 />
          <TermsSections19And20 />
        </div>
      </div>
    </>
  );
};

export default TermsOfService;
