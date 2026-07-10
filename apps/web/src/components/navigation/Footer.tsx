import Image from "next/image";
import Link from "next/link";
import { cloneElement, isValidElement } from "react";
import type { SiteNavigationElement, WebPage, WithContext } from "schema-dts";
import { FooterWordmark } from "@/components/navigation/FooterWordmark";
import JsonLd from "@/components/seo/JsonLd";
import { connect, footerSections } from "@/config/appConfig";
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
      {/* z above the fixed bottom BlurStack (z-1000) so the wordmark and legal
          bar are never blurred by the viewport-edge blur. */}
      <footer className="relative z-[1001] m-0! flex min-h-[50vh] flex-col items-center justify-end gap-6 p-4 font-light sm:gap-7 sm:p-5 lg:p-10 lg:pt-20 lg:pb-5">
        <div className="pointer-events-none absolute inset-x-0 -top-20 z-[-1] h-[30vh] bg-linear-to-t from-background to-transparent" />

        <Image
          src="/images/wallpapers/bands_gradient_black.png"
          alt=""
          fill
          className="z-[-1] object-cover"
        />

        <div className="flex w-full items-center justify-center px-6 sm:px-4">
          <div className="grid w-full max-w-7xl grid-cols-2 gap-10 sm:grid-cols-3 sm:gap-6">
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
        </div>

        {/* Halftone wordmark, constrained to the content width, sitting flush
            on the footer's bottom edge with the legal bar floating over its
            fading lower rows. Negative bottom margin cancels footer padding. */}
        <div className="relative -mb-4 mt-6 w-full max-w-7xl sm:-mb-5">
          <FooterWordmark />

          <div className="absolute inset-x-0 bottom-0">
            <div className="mx-auto flex w-full max-w-7xl flex-col items-center justify-between gap-4 px-4 py-5 text-xs font-light text-zinc-400 sm:flex-row sm:gap-0">
              <div className="flex items-center gap-4">
                {connect.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={link.description}
                    className="text-zinc-400 transition-colors hover:text-zinc-200"
                  >
                    {/* Strip the brand color so icons render monochrome via currentColor. */}
                    {isValidElement(link.icon)
                      ? cloneElement(
                          link.icon as React.ReactElement<{ color?: string }>,
                          { color: "currentColor" },
                        )
                      : link.icon}
                  </Link>
                ))}
              </div>

              <div className="flex items-center gap-2">
                <Link
                  href={"/terms"}
                  className="underline-offset-2 hover:underline"
                >
                  Terms of Use
                </Link>
                <div className="h-4 border-l border-zinc-600" />

                <Link
                  href={"/privacy"}
                  className="underline-offset-2 hover:underline"
                >
                  Privacy Policy
                </Link>
              </div>
            </div>
          </div>
        </div>
      </footer>
    </>
  );
}
