import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { PrivacyIntro } from "./components/PrivacyIntro";
import { PrivacySection1 } from "./components/PrivacySection1";
import { PrivacySection2 } from "./components/PrivacySection2";
import { PrivacySection3And4 } from "./components/PrivacySection3And4";
import { PrivacySection5And6 } from "./components/PrivacySection5And6";
import { PrivacySection7To9 } from "./components/PrivacySection7To9";
import { PrivacySection10To13 } from "./components/PrivacySection10To13";
import { PrivacySection14To16 } from "./components/PrivacySection14To16";

export const metadata: Metadata = generatePageMetadata({
  title: "Privacy Policy",
  description:
    "Review GAIA's Privacy Policy to learn how we collect, use, and protect your personal data while providing our AI assistant services. We prioritize your privacy and data security.",
  path: "/privacy",
  keywords: [
    "Privacy Policy",
    "Data Protection",
    "Personal Data",
    "Privacy",
    "Data Security",
    "GDPR",
    "Data Privacy",
  ],
});

const PrivacyPolicy = () => {
  const privacySchema = generateWebPageSchema(
    "Privacy Policy",
    "Review GAIA's Privacy Policy to learn how we collect, use, and protect your personal data.",
    `${siteConfig.url}/privacy`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Privacy Policy", url: `${siteConfig.url}/privacy` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Privacy Policy", url: `${siteConfig.url}/privacy` },
  ]);

  return (
    <>
      <JsonLd data={[privacySchema, breadcrumbSchema]} />
      <div className="flex w-full flex-col items-center justify-center">
        <div className="privacy-policy w-full max-w-(--breakpoint-xl) px-4 pb-6 pt-24 sm:px-6 lg:px-8">
          <PrivacyIntro />
          <PrivacySection1 />
          <PrivacySection2 />
          <PrivacySection3And4 />
          <PrivacySection5And6 />
          <PrivacySection7To9 />
          <PrivacySection10To13 />
          <PrivacySection14To16 />
        </div>
      </div>
    </>
  );
};

export default PrivacyPolicy;
