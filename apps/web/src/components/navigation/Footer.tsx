import Image from "next/image";
import Link from "next/link";
import type { SiteNavigationElement, WebPage, WithContext } from "schema-dts";
import { FooterWordmark } from "@/components/navigation/FooterWordmark";
import JsonLd from "@/components/seo/JsonLd";
import { footerSections } from "@/config/appConfig";
import { siteConfig } from "@/lib/seo";

export default function Footer() {
  const navigationSchema: WithContext<SiteNavigationElement> = {
    "@context": "https://schema.org",
    "@type": "SiteNavigationElement",
    name: "Footer Navigation",
    url: siteConfig.url,
    hasPart: footerSections.flatMap((section) =>
      section.links
        .filter((link) => !link.external)
        .map(
          (link): WebPage => ({
            "@type": "WebPage",
            name: link.label,
            url: `${siteConfig.url}${link.href}`,
          }),
        ),
    ),
  };

  return (
    <>
      <JsonLd data={navigationSchema} />
      {/* z above the fixed bottom BlurStack (z-1000) so the wordmark is never
          blurred by the viewport-edge blur. */}
      <footer className="relative z-[1001] m-0! flex min-h-[50vh] flex-col items-center justify-end gap-6 p-4 font-light sm:gap-7 sm:p-5 lg:p-10 lg:pt-20 lg:pb-5">
        <div className="pointer-events-none absolute inset-x-0 -top-20 z-[-1] h-[30vh] bg-linear-to-t from-background to-transparent" />

        <Image
          src="/images/wallpapers/bands_gradient_black.png"
          alt=""
          fill
          className="z-[-1] object-cover"
        />

        {/* Columns share the wordmark's container: same max width, centered,
            distributed edge-to-edge so they align with the halftone GAIA. */}
        <div className="flex w-full max-w-7xl flex-wrap justify-between gap-10">
          {footerSections.map((section) => (
            <div key={section.title} className="flex flex-col items-start">
              <div className="mb-3 text-sm font-medium text-foreground">
                {section.title}
              </div>
              {section.links.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  prefetch={false}
                  target={link.external ? "_blank" : undefined}
                  rel={link.external ? "noopener noreferrer" : undefined}
                  className="py-1 text-sm text-zinc-400 transition-colors hover:text-primary"
                >
                  {link.label}
                </Link>
              ))}
            </div>
          ))}
        </div>

        {/* Halftone wordmark, constrained to the content width, sitting flush
            on the footer's bottom edge. Negative bottom margin cancels footer
            padding so the fade lands on the page edge. */}
        <div className="-mb-4 mt-6 w-full max-w-7xl sm:-mb-5">
          <FooterWordmark />
        </div>
      </footer>
    </>
  );
}
