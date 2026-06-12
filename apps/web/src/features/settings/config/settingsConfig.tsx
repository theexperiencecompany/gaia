import {
  Brain02Icon,
  ChartLineData02Icon,
  CreditCardIcon,
  DiscordIcon,
  Link04Icon,
  MessageMultiple02Icon,
  NotificationIcon,
  UserCircleIcon,
  VoiceIdIcon,
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

// Ordered by concern: who you are, how GAIA behaves for you, then billing.
export const settingsPageItems: SettingsMenuItem[] = [
  {
    key: "account",
    label: "Account",
    icon: UserCircleIcon,
    href: "/settings?section=account",
  },
  {
    key: "profile",
    label: "Profile Card",
    icon: PostageStampIcon,
    href: "/settings?section=profile",
  },
  {
    key: "linked-accounts",
    label: "Linked Accounts",
    icon: Link04Icon,
    href: "/settings?section=linked-accounts",
  },
  {
    key: "preferences",
    label: "Preferences",
    icon: MessageMultiple02Icon,
    href: "/settings?section=preferences",
  },
  {
    key: "voice",
    label: "Voices",
    icon: VoiceIdIcon,
    href: "/settings?section=voice",
  },
  {
    key: "memory",
    label: "Memories",
    icon: Brain02Icon,
    href: "/settings?section=memory",
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
