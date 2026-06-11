import {
  AiBrain01Icon,
  ChartLineData02Icon,
  CreditCardIcon,
  DiscordIcon,
  Link03Icon,
  MessageMultiple02Icon,
  NotificationIcon,
  SparklesIcon,
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
    href: "/settings/profile",
  },
  {
    key: "account",
    label: "Account",
    icon: UserCircleIcon,
    href: "/settings/account",
  },
  {
    key: "linked-accounts",
    label: "Linked Accounts",
    icon: Link03Icon,
    href: "/settings/linked-accounts",
  },
  {
    key: "notifications",
    label: "Notifications",
    icon: NotificationIcon,
    href: "/settings/notifications",
  },
  {
    key: "subscription",
    label: "Subscription",
    icon: CreditCardIcon,
    href: "/settings/subscription",
  },
  {
    key: "usage",
    label: "Usage",
    icon: ChartLineData02Icon,
    href: "/settings/usage",
  },
  {
    key: "preferences",
    label: "Preferences",
    icon: MessageMultiple02Icon,
    href: "/settings/preferences",
  },
  {
    key: "memory",
    label: "Memories",
    icon: AiBrain01Icon,
    href: "/settings/memory",
  },
];

export const socialMediaItems: SettingsMenuItem[] = [
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
