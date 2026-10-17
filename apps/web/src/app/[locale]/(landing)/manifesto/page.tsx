import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import About from "@/features/about/components/About";
import { manifestoFAQs } from "@/lib/page-faqs";
import {
  generateAboutPageSchema,
  generateBreadcrumbSchema,
  generateFAQSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Manifesto",
  description:
    "Read why we're building GAIA differently. Unlike Siri, Alexa, or ChatGPT, GAIA is designed to be a real assistant that remembers you, handles your work, and makes your life easier. Learn about our commitment to privacy, open source, and building AI that actually helps.",
  path: "/manifesto",
  keywords: [
    "GAIA manifesto",
    "AI assistant vision",
    "personal assistant",
    "open source AI",
    "privacy focused AI",
    "proactive AI",
    "AI automation",
    "digital assistant",
    "AI transparency",
    "future of AI",
  ],
});

export default function Manifesto() {
  const aboutSchema = generateAboutPageSchema();
  const webPageSchema = generateWebPageSchema(
    "Manifesto",
    "Read why we're building GAIA differently. Our commitment to privacy, open source, and building AI that actually helps.",
    `${siteConfig.url}/manifesto`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Manifesto", url: `${siteConfig.url}/manifesto` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Manifesto", url: `${siteConfig.url}/manifesto` },
  ]);

  const faqSchema = generateFAQSchema(manifestoFAQs);

  return (
    <>
      <JsonLd
        data={[aboutSchema, webPageSchema, breadcrumbSchema, faqSchema]}
      />
      {/* Founder preamble — this is what makes /manifesto distinct from /about:
          About tells our story; the manifesto states what we believe and refuse to compromise on. */}
      <section className="flex w-full justify-center bg-black px-6 pt-28 pb-2">
        <p className="max-w-2xl text-center text-lg font-light tracking-tight text-foreground-600">
          Our About page tells you who we are. This is different — this is what
          I believe about how personal AI should be built, and what I refuse to
          compromise on even when it costs us growth.
        </p>
      </section>
      <About />
    </>
  );
}
