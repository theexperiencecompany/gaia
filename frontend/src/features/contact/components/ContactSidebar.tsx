import {
  DiscordIcon,
  Github,
  LinkedinIcon,
  Mail01Icon,
  SquareLock01Icon,
  TwitterIcon,
  WavingHand01Icon,
  WhatsappIcon,
  YoutubeIcon,
} from "@/icons";

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
];

const socialLinks = [
  {
    ariaLabel: "Discord",
    href: "https://discord.heygaia.io",
    Icon: DiscordIcon,
  },
  {
    ariaLabel: "Twitter",
    href: "https://x.com/trygaia",
    Icon: TwitterIcon,
  },
  {
    ariaLabel: "GitHub",
    href: "https://github.com/theexperiencecompany",
    Icon: Github,
  },
  {
    ariaLabel: "WhatsApp",
    href: "https://whatsapp.heygaia.io",
    Icon: WhatsappIcon,
  },
  {
    ariaLabel: "YouTube",
    href: "https://youtube.com/@heygaia_io",
    Icon: YoutubeIcon,
  },
  {
    ariaLabel: "LinkedIn",
    href: "https://www.linkedin.com/company/heygaia",
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
        {emailLinks.map(({ href, label, Icon }) => (
          <a
            key={label}
            href={href}
            className="text-muted-foreground inline-flex items-center gap-2 text-foreground-500 hover:underline"
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
