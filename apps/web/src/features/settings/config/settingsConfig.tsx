import {
  AiBrain01Icon,
  ChartLineData02Icon,
  ComputerIcon,
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
    href: "/settings?section=profile",
  },
  {
    key: "account",
    label: "Account",
    icon: UserCircleIcon,
    href: "/settings?section=account",
  },
  {
    key: "linked-accounts",
    label: "Linked Accounts",
    icon: Link03Icon,
    href: "/settings?section=linked-accounts",
  },
  {
    key: "notifications",
    label: "Notifications",
    icon: NotificationIcon,
    href: "/settings?section=notifications",
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
  // Only rendered inside the Electron app (filtered in SettingsSidebar).
  {
    key: "desktop",
    label: "Desktop",
    icon: ComputerIcon,
    href: "/settings?section=desktop",
  },
];

/** Settings sections that only make sense inside the desktop app. */
export const DESKTOP_ONLY_SETTINGS_KEYS = new Set(["desktop"]);

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
