import Image from "next/image";
import Link from "next/link";
import type { SiteNavigationElement, WebPage, WithContext } from "schema-dts";

import JsonLd from "@/components/seo/JsonLd";
import { appConfig, connect, footerSections } from "@/config/appConfig";
import { siteConfig } from "@/lib/seo";

const TAGLINE = "GAIA doesn't just answer. It acts.";

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
      <footer className="relative z-1 m-0! flex min-h-[50vh] flex-col items-center justify-end gap-6 p-4 font-light sm:gap-7 sm:p-5 lg:p-10 lg:pt-20 lg:pb-5">
        <div className="pointer-events-none absolute inset-x-0 -top-20 z-[-1] h-[30vh] bg-linear-to-t from-background to-transparent" />

        <Image
          src="/images/wallpapers/bands_gradient_black.png"
          alt=""
          fill
          className="z-[-1] object-cover"
        />

        <div className="flex w-full items-center justify-center px-6 sm:px-4">
          <div className="grid w-full max-w-7xl grid-cols-2 gap-10 sm:grid-cols-5 sm:gap-6">
            <div className="col-span-2 flex flex-col items-start gap-3">
              <Link href="https://twitter.com/madebyexp">
                <Image
                  src="/brand/experience_logo_white.svg"
                  alt="The Experience Company Logo"
                  width={70}
                  height={70}
                />
              </Link>
              <p className="text-sm text-foreground-400">{TAGLINE}</p>
            </div>

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

        <div className="mx-auto mt-6 mb-5 flex w-full max-w-7xl flex-col items-center justify-between gap-4 px-2 py-6 text-xs font-light text-zinc-400 sm:flex-row sm:gap-0 sm:px-4">
          <div className="order-2 flex items-center gap-4 sm:order-1">
            {connect.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                target="_blank"
                rel="noopener noreferrer"
                title={link.description}
                className="transition-opacity hover:opacity-80"
              >
                {link.icon}
              </Link>
            ))}
          </div>
          <div className="order-1 text-center sm:order-2">
            {appConfig.site.copyright}
          </div>

          <div className="order-3 flex items-center gap-2">
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
      </footer>
    </>
  );
}
