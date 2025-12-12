import type { ReactElement } from "react";

import {
  BookOpen02Icon,
  CreditCardPosIcon,
  DiscordIcon,
  Github,
  GlobalIcon,
  HeartHandIcon,
  Home01Icon,
  Idea01Icon,
  LinkedinIcon,
  MapsIcon,
  MessageMultiple02Icon,
  QuillWrite01Icon,
  TwitterIcon,
  WhatsappIcon,
  YoutubeIcon,
} from "@/icons";

export interface AppLink {
  label: string;
  href: string;
  icon?: ReactElement;
  external?: boolean;
  requiresAuth?: boolean;
  guestOnly?: boolean;
  commented?: boolean;
  description?: string;
  hideFooter?: boolean;
}

export interface LinkSection {
  title: string;
  links: AppLink[];
}

export const appConfig = {
  // Site information
  site: {
    name: "GAIA",
    copyright: "Copyright © 2025 The Experience Company. All rights reserved.",
    domain: "heygaia.io",
  },

  // Core link definitions - single source of truth
  links: {
    // Primary navigation links (used in navbar)
    main: [
      {
        href: "/",
        label: "Home",
        icon: <Home01Icon width={20} height={20} color={"currentColor"} />,
        description: "Return to the home page",
      },
    ] as AppLink[],

    // Navigation menu sections
    product: [
      {
        href: "/login",
        label: "Get Started",
        icon: (
          <MessageMultiple02Icon
            width={20}
            height={20}
            color={"currentColor"}
          />
        ),
        requiresAuth: false,
        description: "Sign Up / Login to GAIA",
      },
      {
        href: "/use-cases",
        label: "Use Cases",
        icon: <Idea01Icon width={20} height={20} color={"currentColor"} />,
        description: "Discover workflows and AI prompts",
      },
      {
        href: "/pricing",
        label: "Pricing",
        icon: (
          <CreditCardPosIcon width={20} height={20} color={"currentColor"} />
        ),
        description: "Choose the perfect plan for your needs",
      },
      {
        href: "/roadmap",
        label: "Roadmap",
        icon: <MapsIcon width={20} height={20} color={"currentColor"} />,
        external: true,
        description: "See what's coming next",
      },
    ] as AppLink[],

    resources: [
      {
        href: "/blog",
        label: "Blog",
        icon: (
          <QuillWrite01Icon width={20} height={20} color={"currentColor"} />
        ),
        description: "Read the latest updates and insights",
      },
      {
        href: "/docs",
        label: "Documentation",
        icon: <BookOpen02Icon width={20} height={20} color={"currentColor"} />,
        external: true,
        description: "Comprehensive documentation and guides",
      },
      {
        href: "/request-feature",
        label: "Request a Feature",
        icon: <Idea01Icon width={20} height={20} color={"currentColor"} />,
        external: true,
        description: "Request new features and vote on ideas",
      },
      {
        href: "/status",
        label: "Status",
        icon: <GlobalIcon width={20} height={20} color={"currentColor"} />,
        external: true,
        description: "Check the status of GAIA services",
      },
    ] as AppLink[],

    company: [
      {
        href: "/manifesto",
        label: "Manifesto",
        icon: <GlobalIcon width={20} height={20} color={"currentColor"} />,
        description: "Learn about our mission",
      },
      {
        href: "/contact",
        label: "Contact",
        icon: <HeartHandIcon width={20} height={20} color={"currentColor"} />,
        description: "Get in touch with our team",
      },
      {
        href: "/terms",
        label: "Terms",
        icon: <BookOpen02Icon width={20} height={20} color={"currentColor"} />,
        description: "Terms of service and usage",
        hideFooter: true,
      },
      {
        href: "/privacy",
        label: "Privacy",
        icon: <BookOpen02Icon width={20} height={20} color={"currentColor"} />,
        description: "Our privacy policy",
        hideFooter: true,
      },
    ] as AppLink[],

    connect: [
      {
        href: "/discord",
        label: "Discord",
        icon: <DiscordIcon width={20} height={20} color="#5865f2" />,
        external: true,
        description: "Join Discord Community",
      },
      {
        href: "https://x.com/trygaia",
        label: "Twitter",
        icon: <TwitterIcon width={20} height={20} color="#08a0e9" />,
        external: true,
        description: "Follow us for updates",
      },
      {
        href: "https://github.com/theexperiencecompany",
        label: "GitHub",
        icon: <Github width={20} height={20} color="white" />,
        external: true,
        description: "Check out our open source projects",
      },
      {
        href: "/whatsapp",
        label: "WhatsApp",
        icon: <WhatsappIcon width={20} height={20} color="#25D366" />,
        external: true,
        description: "Join WhatsApp Community",
      },
      {
        href: "https://youtube.com/@heygaia_io",
        label: "YouTube",
        icon: <YoutubeIcon width={25} height={25} color="#FF0000" />,
        external: true,
        description: "Subscribe to our YouTube Channel",
      },
      {
        href: "https://www.linkedin.com/company/heygaia",
        label: "LinkedIn",
        icon: <LinkedinIcon width={20} height={20} color="#0077B5" />,
        external: true,
        description: "Follow our LinkedIn Company Page",
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

  // Footer mapping - references existing link categories
  footerMapping: {
    Product: ["product"],
    Resources: ["resources"],
    Company: ["company"],
  } as Record<string, string[]>,
};

// Utility functions for footer generation
const getFooterSections = (): LinkSection[] => {
  return Object.entries(appConfig.footerMapping).map(([title, categories]) => ({
    title,
    links: categories.flatMap(
      (category) =>
        appConfig.links[category as keyof typeof appConfig.links] || [],
    ),
  }));
};

// Streamlined exports
export const footerSections = getFooterSections();

// Direct access to link categories for navigation
export const { main, product, resources, company, connect, auth } =
  appConfig.links;

// Utility function to get description for a link by label
export const getLinkDescription = (label: string): string => {
  const allLinks = Object.values(appConfig.links).flat();
  const link = allLinks.find((link) => link.label === label);
  return link?.description || "";
};

// Utility function to get a link by label from all categories
export const getLinkByLabel = (label: string): AppLink | undefined => {
  const allLinks = Object.values(appConfig.links).flat();
  return allLinks.find((link) => link.label === label);
};
