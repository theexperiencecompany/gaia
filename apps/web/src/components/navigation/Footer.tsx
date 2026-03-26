import Image from "next/image";
import Link from "next/link";
import React from "react";
import type { SiteNavigationElement, WebPage, WithContext } from "schema-dts";

import JsonLd from "@/components/seo/JsonLd";
import { appConfig, connect, footerSections } from "@/config/appConfig";
import { useUser } from "@/features/auth/hooks/useUser";
import { siteConfig } from "@/lib/seo";

export default function Footer() {
  const user = useUser();
  const isAuthenticated = user?.email;

  const navigationSchema: WithContext<SiteNavigationElement> = {
    "@context": "https://schema.org",
    "@type": "SiteNavigationElement",
    name: "Footer Navigation",
    url: siteConfig.url,
    hasPart: footerSections.flatMap((section) =>
      section.links
        .filter(
          (link) => !link.external && !link.hideFooter && !link.requiresAuth,
        )
        .map(
          (link): WebPage => ({
            "@type": "WebPage",
            name: link.label,
            url: `${siteConfig.url}${link.href}`,
            description: link.description,
          }),
        ),
    ),
  };

  const taglines = [
    "Life. Simplified.",
    "Productivity without friction.",
    "Frictionless productivity",
    "AI that actually works.",
    "Your silent superpower.",
    "Effortless intelligence.",
    "Time is yours again.",
    "The assistant that thinks ahead.",
    "Everything you need. Before you need it.",
    "GAIA doesn’t just answer. It acts.",
    "The future of personal intelligence is already here.",
    "Productivity, personalized.",
    "Your life. Simplified.",
    "One step ahead, always.",
    "Where productivity meets intelligence.",
    "Because your time should be yours.",
    "Your second brain, always on.",
    "Do less. Live more. GAIA takes care of the rest.",
    "Smarter days start here.",
    "Not just an assistant. A partner in progress.",
    "Life, organized. Future, unlocked.",
    "Your silent superpower.",
    "AI that works quietly for you.",
    "Empowering your workflow, silently.",
    "Productivity, reimagined.",
    "Smarter, quieter, better.",
    "Let your work speak.",
    "AI, always in the background.",
    "Unleash silent productivity.",
    "The power behind your ideas.",
    "Work smarter, not louder.",
  ];
  const randomTagline = taglines[Math.floor(Math.random() * taglines.length)];

  return (
    <>
      <JsonLd data={navigationSchema} />
      <div className="relative z-1 m-0! flex flex-col items-center gap-6 p-4 font-light sm:gap-7 sm:p-5 lg:p-10 lg:pt-20 lg:pb-5 min-h-[50vh] ">
        <div className="pointer-events-none absolute inset-x-0 -top-20 z-[-1] h-[30vh] bg-linear-to-t from-background to-transparent" />

        <Image
          src="/images/wallpapers/bands_gradient_black.png"
          alt=""
          fill={true}
          className="mt-10 z-[-1]"
        />
        <div className="flex h-fit w-full items-center justify-center px-6 sm:px-4">
          <div className="grid w-full max-w-7xl grid-cols-2 md:grid-cols-6 gap-6 sm:gap-3">
            <div className="relative -top-1 col-span-2 md:col-span-1 flex h-full flex-col gap-1 text-foreground-600 sm:-top-2">
              <div className="flex w-fit items-center justify-center rounded-xl p-1">
                <iframe
                  src="https://status.heygaia.io/badge?theme=dark"
                  title="GAIA API Status"
                  scrolling="no"
                  height={30}
                  width={186}
                  style={{ colorScheme: "normal" }}
                />
              </div>
              <div className="mt-2 flex flex-col items-start px-2 text-xl font-medium text-white sm:px-3 sm:text-2xl">
                {/* <Link href={"/"}>
                  <Image
                    src="/images/logos/text_w_logo_white.webp"
                    alt="GAIA Logo"
                    width={150}
                    height={45}
                  />
                </Link> */}

                <Link href={"https://twitter.com/madebyexp"}>
                  <Image
                    src="/brand/experience_logo_white.svg"
                    className="my-2"
                    alt="The Experience Company Logo"
                    width={70}
                    height={70}
                  />
                </Link>

                <div className="mt-2 text-sm font-light text-foreground-400">
                  {randomTagline}
                </div>
              </div>
            </div>

            {footerSections.map((section) => (
              <div
                key={section.title}
                className="flex h-full w-full flex-col items-start text-foreground-500 sm:items-end"
              >
                <div className="mb-2 pl-0 text-sm font-medium text-foreground sm:mb-3 sm:pl-2">
                  {section.title}
                </div>
                {section.links

                  .filter(
                    (link) =>
                      ((!link.requiresAuth && !link.guestOnly) ||
                        (link.requiresAuth && isAuthenticated) ||
                        (link.guestOnly && !isAuthenticated)) &&
                      !link.hideFooter,
                  )
                  .sort((a, b) =>
                    section.title === "Built For"
                      ? 0
                      : a.label.localeCompare(b.label, undefined, {
                          sensitivity: "base",
                        }),
                  )
                  .map((link) => (
                    <Link
                      key={link.href}
                      href={link.href}
                      className="group relative flex w-full cursor-pointer justify-start py-1 text-sm sm:justify-end"
                    >
                      <span className="text-foreground-500 transition-colors group-hover:text-primary">
                        {link.label}
                      </span>
                    </Link>
                  ))}
              </div>
            ))}
          </div>
        </div>
        <div className="mx-auto mt-6 flex w-full max-w-7xl flex-col items-center justify-between gap-4 px-2 py-6 pb-3 text-xs font-light text-zinc-300 sm:mt-8 sm:flex-row sm:gap-0 sm:px-4 sm:py-8 lg:mt-10 mb-5">
          <div className="order-2 flex items-center gap-3 sm:order-1">
            {connect.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                target={link.external ? "_blank" : "_self"}
                rel={link.external ? "noopener noreferrer" : undefined}
                className="cursor-pointer text-zinc-300 transition-colors hover:text-foreground"
                title={link.description}
              >
                {React.isValidElement(link.icon)
                  ? React.cloneElement(
                      link.icon as React.ReactElement<{ color?: string }>,
                      {
                        color: undefined,
                      },
                    )
                  : link.icon}
              </Link>
            ))}
          </div>
          <div className="order-1 text-center sm:order-2">
            {appConfig.site.copyright}
          </div>

          <div className="order-3 flex border-separate items-center gap-2 text-center">
            <Link
              href={"/terms"}
              className="underline-offset-2 hover:underline"
            >
              Terms of Use
            </Link>
            <div className="h-4 border-l border-zinc-400" />

            <Link
              href={"/privacy"}
              className="underline-offset-2 hover:underline"
            >
              Privacy Policy
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
