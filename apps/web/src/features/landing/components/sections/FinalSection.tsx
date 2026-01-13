import { Tooltip } from "@heroui/tooltip";
import Image from "next/image";
import Link from "next/link";

import { DiscordIcon, Github, TwitterIcon, WhatsappIcon } from "@/icons";

import { SplitTextBlur } from "../hero/SplitTextBlur";
import GetStartedButton from "../shared/GetStartedButton";

export const SOCIAL_LINKS = [
  {
    href: "https://twitter.com/trygaia",
    ariaLabel: "Twitter Link",
    buttonProps: {
      color: "#1DA1F2",
      className: "rounded-xl text-black!",
      "aria-label": "Twitter Link Button",
    },
    username: "@trygaia",
    icon: <TwitterIcon width={20} height={20} />,
    label: "Twitter",
    description: "Follow us for updates",
    color: "#1DA1F2",
  },
  {
    href: "https://whatsapp.heygaia.io",
    ariaLabel: "WhatsApp Link",
    buttonProps: {
      color: "#25D366",
      className: "rounded-xl text-black!",
      "aria-label": "WhatsApp Link Button",
    },
    icon: <WhatsappIcon width={20} height={20} />,
    label: "WhatsApp",
    description: "Chat with our community",
    color: "#25D366",
  },
  {
    href: "https://discord.heygaia.io",
    ariaLabel: "Discord Link",
    buttonProps: {
      color: "#5865f2",
      className: "rounded-xl text-black!",
      "aria-label": "Discord Link Button",
    },
    icon: <DiscordIcon width={20} height={20} />,
    label: "Discord",
    description: "Join our community server",
    color: "#5865f2",
  },
  {
    href: "https://github.com/theexperiencecompany/gaia",
    ariaLabel: "GitHub Link",
    buttonProps: {
      color: "#1c1c1c",
      className: "rounded-xl text-black!",
      "aria-label": "GitHub Link Button",
    },
    icon: <Github width={20} height={20} />,
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
      <div className="absolute inset-0 h-full w-full">
        <Image
          src="/images/wallpapers/surreal.webp"
          alt="Wallpaper"
          fill
          sizes="100vw"
          className="noisy [mask-image:linear-gradient(to_bottom,transparent_0%,black_20%,black_80%,transparent_100%)] object-cover opacity-70"
          priority
        />
      </div>

      <div
        className={`relative z-2 ${showSocials ? "mb-30" : "mb-10"} flex h-full flex-col items-center justify-start gap-4 sm:gap-6`}
      >
        <SplitTextBlur
          text="Your Life, Supercharged by GAIA"
          delay={0}
          className="z-10 text-center text-[2.2rem] font-medium sm:text-8xl"
        />

        <div className="z-1 mb-6 max-w-(--breakpoint-sm) px-4 py-0 text-center text-base leading-6 font-light tracking-tighter text-foreground-600 sm:px-0 sm:text-xl sm:leading-7 md:text-2xl">
          Join thousands already upgrading their productivity.
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
