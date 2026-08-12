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
      {/* z above the fixed bottom BlurStack (z-10) so the wordmark is never
          blurred by the viewport-edge blur — but below the fixed navbar
          (z-50) so the footer can never paint over navigation. The bands
          wallpaper is shown in FULL — it sets the footer height as a
          full-width banner (natural 3:2 aspect, capped so ultra-wide screens
          don't get an enormous footer) and the content is overlaid on top
          of it. */}
      <footer className="relative z-20 w-full overflow-hidden">
        <Image
          src="/images/wallpapers/bands_gradient_black.png"
          alt=""
          width={1536}
          height={1024}
          priority={false}
          className="pointer-events-none block max-h-[820px] w-full select-none object-cover object-bottom"
        />

        {/* Fade the footer's top edge into the page background above — the
            wallpaper's bright bands start right at its top edge, which
            otherwise reads as a hard line against the last section. The
            via-stop holds the background color a beat longer before easing
            out, so the transition reads as a soft glow instead of a straight
            ramp. */}
        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-48 bg-linear-to-b from-background via-background/50 to-transparent" />

        {/* Film-grain noise over the wallpaper — breaks up gradient banding
            on the beams and gives the footer a tactile, printed feel. SVG
            feTurbulence tile, stitched, blended at low opacity. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 z-20 opacity-[0.05] mix-blend-overlay"
          style={{
            backgroundImage:
              "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160' viewBox='0 0 160 160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E\")",
          }}
        />

        {/* Content overlay: link columns and the halftone wordmark grouped
            together at the bottom, over the bright beams (the black upper half
            of the wallpaper stays empty to blend with the page above). */}
        <div className="absolute inset-0 flex flex-col justify-end gap-8 px-6 sm:gap-10 sm:px-8 lg:px-10">
          <div className="mx-auto flex w-full max-w-7xl flex-wrap justify-between gap-10">
            {footerSections.map((section) => (
              <div key={section.title} className="flex flex-col items-start">
                <div className="mb-3 font-serif text-sm font-medium uppercase tracking-wider text-white">
                  {section.title}
                </div>
                {section.links.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    prefetch={false}
                    target={link.external ? "_blank" : undefined}
                    rel={link.external ? "noopener noreferrer" : undefined}
                    className="py-1 text-sm text-zinc-200 transition-colors hover:text-primary"
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
