import {
  Brain02Icon,
  ChartLineData02Icon,
  ComputerIcon,
  CreditCardIcon,
  DiscordIcon,
  Link04Icon,
  MessageMultiple02Icon,
  NoteEditIcon,
  NotificationIcon,
  UserCircleIcon,
  WhatsappIcon,
} from "@icons";
import { PostageStampIcon } from "@/components/shared/icons";

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
    icon: PostageStampIcon,
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
    icon: Link04Icon,
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
    key: "instructions",
    label: "Custom Instructions",
    icon: NoteEditIcon,
    href: "/settings/instructions",
  },
  {
    key: "memory",
    label: "Memories",
    icon: Brain02Icon,
    href: "/settings/memory",
  },
  // Only rendered inside the Electron app (filtered in SettingsSidebar).
  {
    key: "desktop",
    label: "Desktop",
    icon: ComputerIcon,
    href: "/settings/desktop",
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
