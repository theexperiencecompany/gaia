
import { BarChart3 } from "lucide-react";

import {
  AccountSetting02Icon,
  AiBrain01Icon,
  BookOpen01Icon,
  CreditCardIcon,
  DiscordIcon,
  MessageMultiple02Icon,
  TwitterIcon,
  WhatsappIcon,
} from "@/components/shared/icons";

export interface SettingsMenuItem {
  key: string;
  label: string;
  icon?: React.ElementType;
  href?: string;
  action?: () => void;
  color?: "danger" | "default";
  external?: boolean;
}

export const settingsPageItems: SettingsMenuItem[] = [
  {
    key: "account",
    label: "Account",
    icon: AccountSetting02Icon,
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
    icon: BarChart3,
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
    label: "Memory",
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
