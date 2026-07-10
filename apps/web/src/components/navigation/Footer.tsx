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
          blurred by the viewport-edge blur. The bands wallpaper is shown in
          FULL — it sets the footer height as a full-width banner (natural 3:2
          aspect, capped so ultra-wide screens don't get an enormous footer)
          and the content is overlaid on top of it. */}
      <footer className="relative z-[1001] w-full overflow-hidden">
        <Image
          src="/images/wallpapers/bands_gradient_black.png"
          alt=""
          width={1536}
          height={1024}
          priority={false}
          className="pointer-events-none block max-h-[820px] w-full select-none object-cover object-bottom"
        />

        {/* Content overlay: link columns and the halftone wordmark grouped
            together at the bottom, over the bright beams (the black upper half
            of the wallpaper stays empty to blend with the page above). */}
        <div className="absolute inset-0 flex flex-col justify-end gap-8 px-6 sm:gap-10 sm:px-8 lg:px-10">
          <div className="mx-auto flex w-full max-w-7xl flex-wrap justify-between gap-10">
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

          <div className="mx-auto w-full max-w-7xl">
            <FooterWordmark />
          </div>
        </div>
      </footer>
    </>
  );
}
