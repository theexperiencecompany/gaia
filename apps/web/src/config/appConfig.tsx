import {
  ArrowRight02Icon,
  BlushBrush02Icon,
  BookOpen02Icon,
  ComputerTerminal01Icon,
  ConnectIcon,
  Download02Icon,
  GlobalIcon,
  Home01Icon,
  Idea01Icon,
  MapsIcon,
  MessageMultiple02Icon,
  PackageOpenIcon,
  QuillWrite01Icon,
  UserGroupIcon,
} from "@icons";
import Image from "next/image";
import type { ComponentType, ReactElement } from "react";
import {
  DiscordIcon,
  Github,
  HeartHandIcon,
  LinkedinIcon,
  TwitterIcon,
  WhatsappIcon,
  YoutubeIcon,
} from "@/components/shared/icons";

const BotPlatformIcon = ({
  src,
  alt,
}: {
  src: string;
  alt: string;
}): ReactElement => (
  <div className="relative size-9 shrink-0">
    <Image src={src} alt={alt} fill sizes="36px" className="object-contain" />
  </div>
);

export interface AppLink {
  label: string;
  href: string;
  icon?: ReactElement;
  /** Render the icon without the default pill background (e.g. stacked logos). */
  richIcon?: boolean;
  external?: boolean;
  requiresAuth?: boolean;
  guestOnly?: boolean;
  commented?: boolean;
  description?: string;
  hideNavbar?: boolean;
}

export interface LinkSection {
  title: string;
  links: AppLink[];
}

type NavIconComponent = ComponentType<{
  width?: number;
  height?: number;
  color?: string;
}>;

// Factories keep the link pools declarative one-liners instead of repeating
// the same object/icon shape for every entry.
const navLink = (
  href: string,
  label: string,
  Icon: NavIconComponent,
  description: string,
  extra: Partial<AppLink> = {},
): AppLink => ({
  href,
  label,
  icon: <Icon width={20} height={20} color="currentColor" />,
  description,
  ...extra,
});

const botLink = (
  href: string,
  label: string,
  iconSrc: string,
  description: string,
): AppLink => ({
  href,
  label,
  icon: <BotPlatformIcon src={iconSrc} alt={label} />,
  richIcon: true,
  description,
});

const socialLink = (
  href: string,
  label: string,
  Icon: NavIconComponent,
  color: string,
  description: string,
  size = 20,
): AppLink => ({
  href,
  label,
  icon: <Icon width={size} height={size} color={color} />,
  external: true,
  description,
});

export const appConfig = {
  // Site information
  site: {
    name: "GAIA",
    domain: "heygaia.io",
    mobileWaitlist:
      "https://heygaia.notion.site/307023640e7b802ca404dee12cb04e89?pvs=105",
  },

  // Core link definitions - single source of truth
  links: {
    // Primary navigation links (used in navbar)
    main: [
      navLink("/", "Home", Home01Icon, "Return to the home page"),
    ] as AppLink[],

    // Navigation menu sections
    product: [
      navLink(
        "/use-cases",
        "Use Cases",
        Idea01Icon,
        "Here's what GAIA can do for you",
      ),
      navLink(
        "/marketplace",
        "Integrations",
        ConnectIcon,
        "Connect GAIA to the tools you already use",
      ),
      navLink(
        "/download",
        "Download",
        Download02Icon,
        "GAIA on your Mac, phone, and browser",
      ),
      navLink(
        "/cli",
        "Self-Host CLI",
        ComputerTerminal01Icon,
        "Keep your data on your own infrastructure",
      ),
      botLink(
        "/whatsapp",
        "WhatsApp",
        "/images/icons/macos/whatsapp.webp",
        "Chat with GAIA on WhatsApp",
      ),
      botLink(
        "/bots",
        "Telegram",
        "/images/icons/macos/telegram.webp",
        "Chat with GAIA on Telegram",
      ),
      botLink(
        "/slack-bot",
        "Slack",
        "/images/icons/macos/slack.webp",
        "Bring GAIA into your workspace",
      ),
      botLink(
        "/discord-bot",
        "Discord",
        "/images/icons/macos/discord.webp",
        "Add GAIA to your server",
      ),
      botLink(
        "/bots",
        "iMessage",
        "/images/icons/macos/imessage.webp",
        "Text GAIA from your iPhone",
      ),
      navLink(
        "/features",
        "Features",
        MapsIcon,
        "Every capability in one place",
        {
          hideNavbar: true,
        },
      ),
      navLink(
        "/for",
        "Tailored For Your Role",
        UserGroupIcon,
        "Workflows tuned for your job, not generic ones",
        { hideNavbar: true },
      ),
      navLink(
        "/compare",
        "Compare",
        GlobalIcon,
        "Side-by-side with ChatGPT, Claude, and Poke",
        { hideNavbar: true },
      ),
    ] as AppLink[],

    resources: [
      navLink("/roadmap", "Roadmap", MapsIcon, "What we're shipping next", {
        external: true,
      }),
      navLink(
        "/blog",
        "Blog",
        QuillWrite01Icon,
        "Stories, lessons, and product updates",
      ),
      navLink(
        "https://docs.heygaia.io/release-notes",
        "Release Notes",
        PackageOpenIcon,
        "What's new, what's fixed, what's better",
        { external: true },
      ),
      navLink(
        "/about",
        "About",
        GlobalIcon,
        "Learn about GAIA and the team behind it",
      ),
      navLink(
        "/request-feature",
        "Request a Feature",
        Idea01Icon,
        "Tell us what to build next",
        { external: true },
      ),
      navLink(
        "/learn",
        "Glossary",
        BookOpen02Icon,
        "AI and productivity terms explained",
        { hideNavbar: true },
      ),
      navLink(
        "/alternative-to",
        "Alternatives",
        ArrowRight02Icon,
        "See which tools GAIA replaces and how it compares",
        { hideNavbar: true },
      ),
      navLink(
        "/automate",
        "Automation Combos",
        ConnectIcon,
        "Recipes for connecting any two tools",
        { hideNavbar: true },
      ),
      navLink(
        "/feed.xml",
        "RSS Feed",
        GlobalIcon,
        "Subscribe to all GAIA pages and updates via RSS",
        { hideNavbar: true },
      ),
    ] as AppLink[],

    company: [
      navLink("/manifesto", "Manifesto", GlobalIcon, "Our mission and vision"),
      navLink(
        "/brand",
        "Branding",
        BlushBrush02Icon,
        "Brand guidelines and downloadable assets",
      ),
      navLink(
        "/thanks",
        "Tools We Love",
        HeartHandIcon,
        "Open source tools that power GAIA",
      ),
      navLink(
        "/contact",
        "Contact",
        HeartHandIcon,
        "Get in touch with our team",
      ),
      navLink("/terms", "Terms", BookOpen02Icon, "Terms of service and usage"),
      navLink("/privacy", "Privacy", BookOpen02Icon, "Our privacy policy"),
    ] as AppLink[],

    connect: [
      socialLink(
        "https://discord.heygaia.io",
        "Discord",
        DiscordIcon,
        "#5865f2",
        "Join Discord Community",
      ),
      socialLink(
        "https://x.com/trygaia",
        "Twitter",
        TwitterIcon,
        "#08a0e9",
        "Follow us for updates",
      ),
      socialLink(
        "https://github.com/theexperiencecompany",
        "GitHub",
        Github,
        "white",
        "Check out our open source projects",
      ),
      socialLink(
        "https://whatsapp.heygaia.io",
        "WhatsApp",
        WhatsappIcon,
        "#25D366",
        "Join WhatsApp Community",
      ),
      socialLink(
        "https://youtube.com/@theexperiencecompany",
        "YouTube",
        YoutubeIcon,
        "#FF0000",
        "Subscribe to our YouTube Channel",
        25,
      ),
      socialLink(
        "https://www.linkedin.com/company/heygaia",
        "LinkedIn",
        LinkedinIcon,
        "#0077B5",
        "Follow our LinkedIn Company Page",
      ),
    ] as AppLink[],

    personas: [
      {
        href: "/for/startup-founders",
        label: "Startup Founders",
        description: "AI chief of staff for founders",
        hideNavbar: true,
      },
      {
        href: "/for/software-developers",
        label: "Software Developers",
        description: "Automate standups and GitHub workflows",
        hideNavbar: true,
      },
      {
        href: "/for/sales-professionals",
        label: "Sales Professionals",
        description: "AI CRM monitor and follow-up automation",
        hideNavbar: true,
      },
      {
        href: "/for/product-managers",
        label: "Product Managers",
        description: "Automate stakeholder updates and sprint reports",
        hideNavbar: true,
      },
      {
        href: "/for/engineering-managers",
        label: "Engineering Managers",
        description: "1:1 prep, sprint reports, and team analytics",
        hideNavbar: true,
      },
      {
        href: "/for/agency-owners",
        label: "Agency Owners",
        description: "Run 10 clients without losing your mind",
        hideNavbar: true,
      },
      {
        href: "/for",
        label: (
          <div className="flex items-center gap-1">
            <span>View All Roles</span>
            <ArrowRight02Icon width={15} height={15} />
          </div>
        ),
        description: "See all personas GAIA is built for",
        hideNavbar: true,
      },
    ] as AppLink[],

    // Authentication related links
    auth: [
      {
        href: "/login",
        label: "Login",
        guestOnly: true,
      },
      {
        href: "/signup",
        label: "Get Started",
        guestOnly: true,
      },
      {
        href: "/c",
        label: "Chat",
        icon: <MessageMultiple02Icon width={17} color={"currentColor"} />,
        requiresAuth: true,
      },
    ] as AppLink[],
  },
};

// Curated footer — hand-picked and hand-ordered, independent of the navbar
// link pool. Programmatic SEO pages (glossary, alternatives, automation
// combos, personas) are intentionally excluded; they are linked from their
// hub pages and sitemaps instead.
export const footerSections: LinkSection[] = [
  {
    title: "Product",
    links: [
      { label: "Download", href: "/download" },
      { label: "Use Cases", href: "/use-cases" },
      { label: "Marketplace", href: "/marketplace" },
      { label: "Bots", href: "/bots" },
      { label: "Pricing", href: "/pricing" },
      { label: "Roadmap", href: "/roadmap", external: true },
    ],
  },
  {
    title: "Resources",
    links: [
      {
        label: "Documentation",
        href: "https://docs.heygaia.io",
        external: true,
      },
      { label: "Blog", href: "/blog" },
      {
        label: "Release Notes",
        href: "https://docs.heygaia.io/release-notes",
        external: true,
      },
      { label: "Status", href: "/status", external: true },
      { label: "Request a Feature", href: "/request-feature", external: true },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "About", href: "/about" },
      { label: "Manifesto", href: "/manifesto" },
      { label: "Contact", href: "/contact" },
      { label: "Branding", href: "/brand" },
    ],
  },
  {
    title: "Legal",
    links: [
      { label: "Terms of Use", href: "/terms" },
      { label: "Privacy Policy", href: "/privacy" },
    ],
  },
];

// Direct access to link categories for navigation
export const { product, resources, company, connect, auth } = appConfig.links;

// Utility function to get a link by label from all categories
export const getLinkByLabel = (label: string): AppLink | undefined => {
  const allLinks = Object.values(appConfig.links).flat();
  return allLinks.find((link) => link.label === label);
};
