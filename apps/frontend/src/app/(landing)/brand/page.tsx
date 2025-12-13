import type { Metadata } from "next";
import Link from "next/link";

import JsonLd from "@/components/seo/JsonLd";
import { generatePageMetadata } from "@/lib/seo";

import { BrandAssets } from "./components/BrandAssets";
import { BrandColors } from "./components/BrandColors";
import { BrandGuidelines } from "./components/BrandGuidelines";
import { DownloadAll } from "./components/DownloadAll";

export const metadata: Metadata = generatePageMetadata({
  title: "Brand Guidelines & Press Kit",
  description:
    "Download official brand assets, logos, wordmarks, and press kit materials for The Experience Company and GAIA. Access high-resolution logos in multiple formats for press, media, and partnerships.",
  path: "/brand",
  keywords: [
    "brand guidelines",
    "press kit",
    "brand assets",
    "logo download",
    "media kit",
    "brand resources",
    "company logos",
    "wordmark",
    "the experience company",
    "the experience company brand",
    "gaia branding",
    "gaia brand assets",
    "press materials",
    "marketing assets",
    "brand identity",
    "logo guidelines",
    "design assets",
    "brand manual",
    "visual identity",
  ],
  image: "/og-image.webp",
});

export default function BrandPage() {
  const brandSchema = {
    "@context": "https://schema.org" as const,
    "@type": "WebPage" as const,
    name: "Brand Guidelines & Press Kit",
    description:
      "Official brand assets and press kit for The Experience Company and GAIA",
    url: "https://heygaia.io/brand",
    about: [
      {
        "@type": "Organization" as const,
        name: "The Experience Company",
        url: "https://heygaia.io",
      },
      {
        "@type": "Organization" as const,
        name: "GAIA",
        alternateName: "General-purpose AI Assistant",
        url: "https://heygaia.io",
      },
    ],
  };

  return (
    <>
      <JsonLd data={brandSchema} />
      <div className="flex min-h-screen w-screen justify-center py-28">
        <div className="w-full max-w-(--breakpoint-lg) space-y-16 px-6">
          <section>
            <div className="mx-auto max-w-3xl text-center">
              <h1 className="mb-6 text-4xl font-medium tracking-tight md:text-5xl">
                Brand Guidelines
              </h1>
              <p className="mb-8 text-lg text-foreground-600 dark:text-foreground-400">
                Resources for presenting The Experience Company and GAIA brands
                consistently and professionally. Download our logos, wordmarks,
                and brand assets for press, media, and partnership use.
              </p>
              <DownloadAll />
            </div>
          </section>

          <section>
            <BrandGuidelines />
          </section>

          <section>
            <BrandAssets />
          </section>

          <section>
            <BrandColors />
          </section>

          <section>
            <div className="mx-auto max-w-3xl">
              <h2 className="mb-8 text-3xl font-medium">Usage Guidelines</h2>
              <div className="space-y-8">
                <div>
                  <h3 className="mb-3 text-xl font-semibold">Logo Usage</h3>
                  <div className="space-y-3 text-foreground-600 dark:text-foreground-400">
                    <p>
                      Use the full logo with wordmark whenever space allows. For
                      tight layouts or logo grids, the standalone icon is
                      acceptable.
                    </p>
                    <p>
                      Monochrome usage is preferred. Use white logos on dark
                      backgrounds and black logos on light backgrounds for
                      optimal visibility and brand consistency.
                    </p>
                  </div>
                </div>

                <div>
                  <h3 className="mb-3 text-xl font-semibold">
                    Spacing & Sizing
                  </h3>
                  <div className="space-y-3 text-foreground-600 dark:text-foreground-400">
                    <p>
                      Provide plenty of space around our brand assets. Make them
                      big or make them small, but give them room to breathe.
                      They shouldn't feel cramped or cluttered.
                    </p>
                    <p>
                      Maintain clear space around our logos equal to the height
                      of the logo icon. This ensures the logo has room to
                      breathe and maintains visual impact.
                    </p>
                    <p>
                      The minimum logo size should be 32px in height for digital
                      use and 0.5 inches for print to maintain legibility.
                    </p>
                  </div>
                </div>

                <div className="rounded-2xl bg-warning-50 p-4 dark:border-warning-900 dark:bg-warning-950">
                  <h3 className="mb-2 text-lg font-semibold text-warning">
                    Don'ts
                  </h3>
                  <ul className="list-inside list-disc space-y-1 text-warning-800 dark:text-warning-300 text-sm">
                    <li>
                      Do not alter, rotate, or modify the logos in any way
                    </li>
                    <li>
                      Do not change the logo colors outside the approved palette
                    </li>
                    <li>
                      Do not place logos on busy backgrounds that reduce
                      legibility
                    </li>
                    <li>Do not stretch or distort the logo proportions</li>
                    <li>
                      Do not use the logos to imply endorsement without
                      permission
                    </li>
                  </ul>
                </div>

                <div className="rounded-3xl bg-zinc-800 p-4 dark:border-foreground-800 dark:bg-foreground-950">
                  <p className="mb-3">
                    <strong className="text-zinc-300">Important:</strong> The
                    provided graphics are proprietary and protected under
                    intellectual property laws. Please do not alter these files
                    in any way, display these graphics in a way that implies a
                    relationship, affiliation, or endorsement by The Experience
                    Company of your product, service, or business, or use these
                    graphics as part of your own product, business, or service's
                    name.
                  </p>
                  <p className="text-zinc-300">
                    For questions or special requests, please{" "}
                    <Link
                      href="/contact"
                      className="text-primary hover:underline"
                    >
                      contact us
                    </Link>
                    .
                  </p>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
