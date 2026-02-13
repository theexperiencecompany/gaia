import {
  AiBrain01Icon,
  BookOpen01Icon,
  ChartLineData02Icon,
  CreditCardIcon,
  DiscordIcon,
  MessageMultiple02Icon,
  SparklesIcon,
  TwitterIcon,
  UserCircleIcon,
  WhatsappIcon,
} from "@icons";

export interface SettingsMenuItem {
  key: string;
  label: string;
  // Icons are SVG components — accept standard SVG props
  icon?: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  href?: string;
  action?: () => void;
  color?: "danger" | "default";
  external?: boolean;
}

export const settingsPageItems: SettingsMenuItem[] = [
  {
    key: "profile",
    label: "Profile Card",
    icon: SparklesIcon,
    href: "/settings?section=profile",
  },
  {
    key: "account",
    label: "Account",
    icon: UserCircleIcon,
    href: "/settings?section=account",
  },
  {
    key: "subscription",
    label: "Subscription",
    icon: CreditCardIcon,
    href: "/settings?section=subscription",
  },
  {
    key: "usage",
    label: "Usage",
    icon: ChartLineData02Icon,
    href: "/settings?section=usage",
  },
  {
    key: "preferences",
    label: "Preferences",
    icon: MessageMultiple02Icon,
    href: "/settings?section=preferences",
  },
  {
    key: "memory",
    label: "Memories",
    icon: AiBrain01Icon,
    href: "/settings?section=memory",
  },
];

export const socialMediaItems: SettingsMenuItem[] = [
  {
    key: "twitter",
    label: "Follow Us",
    icon: TwitterIcon,
    external: true,
  },
  {
    key: "discord",
    label: "Join Discord",
    icon: DiscordIcon,
    external: true,
  },
  {
    key: "whatsapp",
    label: "Join WhatsApp",
    icon: WhatsappIcon,
    external: true,
  },
];

export const resourceItems: SettingsMenuItem[] = [
  {
    key: "documentation",
    label: "Documentation",
    icon: BookOpen01Icon,
    external: true,
  },
];
