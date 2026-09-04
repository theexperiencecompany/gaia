import Image from "next/image";
import Link from "next/link";
import { cloneElement, isValidElement } from "react";
import type { SiteNavigationElement, WebPage, WithContext } from "schema-dts";
import { FooterWordmark } from "@/components/navigation/FooterWordmark";
import JsonLd from "@/components/seo/JsonLd";
import { GrainOverlay } from "@/components/ui/GrainOverlay";
import { connect, footerSections } from "@/config/appConfig";
import { siteConfig } from "@/lib/seo";

export default function Footer() {
  const navigationSchema: WithContext<SiteNavigationElement> = {
    "@context": "https://schema.org",
    "@type": "SiteNavigationElement",
    name: "Footer Navigation",
    url: siteConfig.url,
    // Single pass: skip external links while building the WebPage entries.
    hasPart: footerSections.flatMap((section) => {
      const pages: WebPage[] = [];
      for (const link of section.links) {
        if (link.external) continue;
        pages.push({
          "@type": "WebPage",
          name: link.label,
          url: `${siteConfig.url}${link.href}`,
        });
      }
      return pages;
    }),
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
          className="pointer-events-none z-0 origin-bottom scale-150 select-none object-cover object-bottom"
        />

        {/* Fade the footer's top edge into the page background above, so the
            wallpaper's edge never reads as a hard line against the last
            section. The via-stop holds the background color a beat longer
            before easing out, so the transition reads as a soft glow instead
            of a straight ramp. z-0 (not a higher layer) keeps the fade in the
            same paint step as the wallpaper, above it by DOM order but below
            the content below — otherwise its lower half washes over the link
            column headings, which sit inside the fade's 12rem band. */}
        <div className="pointer-events-none absolute inset-x-0 top-0 z-0 h-48 bg-linear-to-b from-background via-background/50 to-transparent" />

        {/* Film-grain over the wallpaper — breaks up gradient banding in the
            glow and gives the footer a tactile, printed feel. */}
        <GrainOverlay variant="surface" className="z-20" />

        {/* Content: link columns and the halftone wordmark. This is what sets
            the footer's height — the top padding leaves the dark upper part of
            the glow visible so the footer blends into the page above.
            Deliberately NO z-index: a z-index here would create a stacking
            context, which isolates blending and would leave the wordmark's
            mix-blend-mode with an empty backdrop instead of the wallpaper.
            Paint order over the wallpaper comes from `relative` + DOM order. */}
        <div className="relative flex flex-col gap-8 px-6 pt-24 pb-1 sm:gap-10 sm:px-8 lg:px-10">
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

          {/* Bottom bar under the wordmark. A 3-column grid rather than
              flex+space-between, so the company mark is centered against the
              footer itself and does not drift as the status badge and the
              social row change width. */}
          <div className="mx-auto grid w-full max-w-7xl grid-cols-1 items-center justify-items-center gap-6 sm:grid-cols-3">
            {/* Cross-origin frame: `ph-no-capture` stops PostHog from reaching
                into it, which throws a SecurityError. The badge endpoint is
                static HTML/CSS with a target="_blank" link, so `allow-popups`
                is the only capability it needs — scripts, forms, and same-origin
                access stay blocked. */}
            <iframe
              src="https://status.heygaia.io/badge?theme=dark"
              title="GAIA API Status"
              className="ph-no-capture sm:justify-self-start"
              scrolling="no"
              height={30}
              width={186}
              sandbox="allow-popups"
              style={{ colorScheme: "normal" }}
            />

            <Link
              href="https://twitter.com/madebyexp"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-sm text-zinc-200 transition-colors hover:text-primary"
            >
              {/* Sized to the text's line box so the mark and the wordmark
                  share one height instead of the mark towering over it. */}
              <Image
                src="/brand/experience_logo_white.svg"
                alt=""
                width={20}
                height={20}
                className="h-5 w-5"
              />
              The Experience Company Inc.
            </Link>

            <div className="flex items-center gap-4 sm:justify-self-end">
              {connect.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  target={link.external ? "_blank" : undefined}
                  rel={link.external ? "noopener noreferrer" : undefined}
                  title={link.description}
                  aria-label={link.label}
                  className="text-zinc-200 transition-colors hover:text-primary"
                >
                  {/* Drop each icon's brand color so the row reads as one set
                      and inherits the hover state. */}
                  {isValidElement<{ color?: string }>(link.icon)
                    ? cloneElement(link.icon, { color: undefined })
                    : link.icon}
                </Link>
              ))}
            </div>
          </div>
        </div>
      </footer>
    </>
  );
}
