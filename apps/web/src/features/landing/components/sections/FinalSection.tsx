import { Tooltip } from "@heroui/tooltip";
import Image from "next/image";
import Link from "next/link";

import { DiscordIcon, Github, TwitterIcon, WhatsappIcon } from "@/icons";

import { SplitTextBlur } from "../hero/SplitTextBlur";
import GetStartedButton from "../shared/GetStartedButton";

export const SOCIAL_LINKS = [
  {
    href: "https://twitter.com/trygaia",
    ariaLabel: "Twitter",
    buttonProps: {
      color: "#1a8cd8",
      className: "rounded-xl text-white!",
      "aria-label": "Twitter Link Button",
    },
    username: "@trygaia",
    icon: <TwitterIcon width={20} height={20} aria-hidden="true" />,
    label: "Twitter",
    description: "Follow us for updates",
    color: "#1a8cd8",
  },
  {
    href: "https://whatsapp.heygaia.io",
    ariaLabel: "WhatsApp",
    buttonProps: {
      color: "#1a9e4a",
      className: "rounded-xl text-white!",
      "aria-label": "WhatsApp Link Button",
    },
    icon: <WhatsappIcon width={20} height={20} aria-hidden="true" />,
    label: "WhatsApp",
    description: "Chat with our community",
    color: "#1a9e4a",
  },
  {
    href: "https://discord.heygaia.io",
    ariaLabel: "Discord",
    buttonProps: {
      color: "#5865f2",
      className: "rounded-xl text-white!",
      "aria-label": "Discord Link Button",
    },
    icon: <DiscordIcon width={20} height={20} aria-hidden="true" />,
    label: "Discord",
    description: "Join our community server",
    color: "#5865f2",
  },
  {
    href: "https://github.com/theexperiencecompany/gaia",
    ariaLabel: "GitHub",
    buttonProps: {
      color: "#1c1c1c",
      className: "rounded-xl text-white!",
      "aria-label": "GitHub Link Button",
    },
    icon: <Github width={20} height={20} aria-hidden="true" />,
    label: "GitHub",
    description: "Star and contribute",
    color: "#000000",
  },
];

export default function FinalSection({
  showSocials = true,
}: {
  showSocials?: boolean;
}) {
  return (
    <div className="relative z-1 m-0! flex min-h-[90vh] w-screen flex-col items-center justify-center gap-4 overflow-hidden px-4 sm:px-6">
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-[20vh] bg-linear-to-t from-background to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 -top-5 z-10 h-[30vh] bg-linear-to-b from-background to-transparent" />
      <div className="absolute inset-0 h-full w-full">
        <Image
          src="/images/wallpapers/landscape.webp"
          alt="Wallpaper"
          fill
          className="object-cover"
          sizes="100vw"
          priority
        />
      </div>

      <div
        className={`relative z-2 ${showSocials ? "mb-30" : "mb-10"} flex h-full flex-col items-center justify-start gap-4`}
      >
        <SplitTextBlur
          text="Stop doing everything yourself."
          delay={0}
          className="z-10 text-center text-[2.2rem] font-medium sm:text-8xl tracking-tight leading-snug"
        />

        <div className="z-1 mb-6 max-w-(--breakpoint-sm) px-4 py-0 text-center text-base leading-6 font-light tracking-tighter text-foreground-600 sm:px-0 sm:text-xl sm:leading-7 md:text-2xl">
          Join thousands who stopped doing manually what GAIA can handle for
          them.
        </div>
        <GetStartedButton />

        {showSocials && (
          <div className="mt-4 flex items-center gap-3 sm:mt-6 sm:gap-2">
            {SOCIAL_LINKS.map(
              ({ href, ariaLabel, buttonProps, icon, label }, index) => {
                const color = `hover:text-[${buttonProps.color}]`;
                return (
                  <Tooltip
                    content={label}
                    placement="bottom"
                    key={index + href}
                  >
                    <Link
                      href={href}
                      aria-label={ariaLabel}
                      className={`flex w-10 scale-110 justify-center p-1 transition hover:scale-125 sm:w-10 sm:scale-125 sm:hover:scale-150 ${color}`}
                    >
                      {icon}
                    </Link>
                  </Tooltip>
                );
              },
            )}
          </div>
        )}
      </div>
    </div>
  );
}
