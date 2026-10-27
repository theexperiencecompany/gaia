"use client";

import { Tooltip } from "@heroui/tooltip";
import Image from "next/image";
import Link from "next/link";
import {
  DiscordIcon,
  Github,
  TwitterIcon,
  WhatsappIcon,
} from "@/components/shared/icons";
import { siteConfig } from "@/lib/seo";

import GetStartedButton from "../shared/GetStartedButton";
import { TextSoftBlurIn } from "../shared/TextSoftBlurIn";

const SOCIAL_LINKS = [
  {
    href: siteConfig.links.twitter,
    ariaLabel: "GAIA on X",
    icon: <TwitterIcon width={20} height={20} aria-hidden="true" />,
    label: "Twitter",
  },
  {
    href: siteConfig.links.whatsapp,
    ariaLabel: "GAIA on WhatsApp",
    icon: <WhatsappIcon width={20} height={20} aria-hidden="true" />,
    label: "WhatsApp",
  },
  {
    href: siteConfig.links.discord,
    ariaLabel: "GAIA on Discord",
    icon: <DiscordIcon width={20} height={20} aria-hidden="true" />,
    label: "Discord",
  },
  {
    href: siteConfig.links.repo,
    ariaLabel: "GAIA on GitHub",
    icon: <Github width={20} height={20} aria-hidden="true" />,
    label: "GitHub",
  },
];

export default function FinalSection({
  showSocials = true,
}: {
  showSocials?: boolean;
}) {
  return (
    <div className="relative w-full px-4 py-10 sm:px-6 sm:py-14">
      <div className="relative mx-auto flex min-h-[440px] w-full max-w-7xl flex-col items-center justify-center gap-4 overflow-hidden rounded-[2.5rem] px-4 py-20 sm:min-h-[520px] sm:px-6">
        <Image
          src="/images/wallpapers/creation_of_adam.png"
          alt=""
          fill
          sizes="100vw"
          className="z-0 object-cover object-center"
        />
        {/* Legibility scrim over the Earth photo. */}
        <div className="pointer-events-none absolute inset-0 z-10 bg-black/30" />
        {/* Soft outline in the design language — slightly thick, low opacity. */}
        <div className="pointer-events-none absolute inset-0 z-30 rounded-[2.5rem] border-2 border-white/10" />

        <div className="relative z-20 flex w-full max-w-5xl flex-col items-center justify-center gap-4 text-center">
          <TextSoftBlurIn
            text="Stop doing everything yourself"
            as="h2"
            className="z-10 px-2 text-center text-[clamp(2.8rem,8.3vw,5rem)] leading-[1.05] font-serif font-normal tracking-tight text-white md:text-6xl"
            gradient="linear-gradient(to bottom, #ffffff, #dbdbdb)"
          />

          <p className="z-1 mb-3 max-w-sm px-4 text-base leading-6 font-light text-zinc-200 sm:mb-6 sm:max-w-(--breakpoint-md) sm:px-0 sm:text-xl sm:leading-7 md:text-2xl">
            Join thousands of professionals who gave their grunt work to GAIA.
          </p>

          <GetStartedButton
            btnColor="#00bbff"
            classname="w-full max-w-xs sm:w-auto text-sm sm:text-lg h-9 sm:h-12 px-6 rounded-xl hover:scale-105"
            text="Get Started"
          />

          {showSocials && (
            <div className="mt-3 flex flex-wrap items-center justify-center gap-4 text-zinc-300 sm:mt-6 max-[700px]:hidden">
              {SOCIAL_LINKS.map(({ href, ariaLabel, icon, label }) => (
                <Tooltip content={label} placement="bottom" key={href}>
                  <Link
                    href={href}
                    aria-label={ariaLabel}
                    className="flex justify-center p-1 transition hover:scale-110 hover:text-white"
                  >
                    {icon}
                  </Link>
                </Tooltip>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
