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
          (z-50) so the footer can never paint over navigation. The footer's
          height is set by its own content; the glow wallpaper fills behind it
          and is anchored to the bottom so the brightest part of the glow sits
          under the wordmark on every viewport. */}
      <footer className="relative z-20 w-full overflow-hidden">
        <Image
          src="/images/wallpapers/subtle_glow_deep_blues.webp"
          alt=""
          fill
          sizes="100vw"
          priority={false}
          className="pointer-events-none z-0 select-none object-cover object-bottom"
        />

        {/* Fade the footer's top edge into the page background above, so the
            wallpaper's edge never reads as a hard line against the last
            section. The via-stop holds the background color a beat longer
            before easing out, so the transition reads as a soft glow instead
            of a straight ramp. */}
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

        {/* Content: link columns and the halftone wordmark. This is what sets
            the footer's height — the top padding leaves the dark upper part of
            the glow visible so the footer blends into the page above.
            Deliberately NO z-index: a z-index here would create a stacking
            context, which isolates blending and would leave the wordmark's
            mix-blend-mode with an empty backdrop instead of the wallpaper.
            Paint order over the wallpaper comes from `relative` + DOM order. */}
        <div className="relative flex flex-col gap-8 px-6 pt-40 pb-8 sm:gap-10 sm:px-8 lg:px-10">
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
