import {
  Calendar01Icon,
  Mail01Icon,
  SquareLock01Icon,
  WavingHand01Icon,
} from "@icons";
import {
  DiscordIcon,
  Github,
  LinkedinIcon,
  TwitterIcon,
  WhatsappIcon,
} from "@/components/shared/icons";
import { siteConfig } from "@/lib/seo";

const emailLinks = [
  {
    href: "mailto:contact@heygaia.io",
    label: "contact@heygaia.io",
    Icon: Mail01Icon,
  },
  {
    href: "mailto:ceo@heygaia.io",
    label: "ceo@heygaia.io",
    Icon: WavingHand01Icon,
  },
  {
    href: "mailto:security@heygaia.io",
    label: "security@heygaia.io",
    Icon: SquareLock01Icon,
  },
  {
    href: "https://cal.com/aryanranderiya",
    label: "Book a call",
    Icon: Calendar01Icon,
    external: true,
  },
];

const socialLinks = [
  {
    ariaLabel: "Discord",
    href: siteConfig.links.discord,
    Icon: DiscordIcon,
  },
  {
    ariaLabel: "Twitter",
    href: siteConfig.links.twitter,
    Icon: TwitterIcon,
  },
  {
    ariaLabel: "GitHub",
    href: siteConfig.links.repo,
    Icon: Github,
  },
  {
    ariaLabel: "WhatsApp",
    href: siteConfig.links.whatsapp,
    Icon: WhatsappIcon,
  },
  {
    ariaLabel: "LinkedIn",
    href: siteConfig.links.linkedin,
    Icon: LinkedinIcon,
  },
];

export default function ContactSidebar() {
  return (
    <div className="grid gap-10">
      <section aria-labelledby="email-heading">
        <h3
          id="email-heading"
          className="mb-3 text-base font-semibold tracking-tight"
        >
          Get in Touch
        </h3>
        {emailLinks.map(({ href, label, Icon, external }) => (
          <a
            key={label}
            href={href}
            className="text-muted-foreground inline-flex items-center gap-2 text-foreground-500 hover:underline"
            {...(external
              ? { target: "_blank", rel: "noopener noreferrer" }
              : {})}
          >
            <Icon className="size-5" aria-hidden="true" />
            {label}
          </a>
        ))}
      </section>

      <section aria-labelledby="follow-heading">
        <h3
          id="follow-heading"
          className="text-base font-semibold tracking-tight"
        >
          Socials
        </h3>
        <div className="mt-3 flex items-center gap-2 text-foreground-500">
          {socialLinks.map(({ ariaLabel, href, Icon }) => (
            <a
              key={ariaLabel}
              aria-label={ariaLabel}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-foreground"
            >
              <Icon className="size-5" />
            </a>
          ))}
        </div>
      </section>
    </div>
  );
}
