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
  PuzzleIcon,
  UserCircleIcon,
  VoiceIdIcon,
  WhatsappIcon,
} from "@icons";
import Image from "next/image";
import type { ReactNode } from "react";
import { PostageStampIcon } from "@/components/shared/icons";
import { providerFaviconUrl } from "@/features/settings/api/providersApi";

export interface SettingsMenuItem {
  key: string;
  label: string;
  // Icons are SVG components — accept standard SVG props
  icon?: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  /** Pre-rendered brand mark for entries without an @icons glyph (e.g. favicons). */
  iconElement?: ReactNode;
  href?: string;
  action?: () => void;
  color?: "danger" | "default";
  external?: boolean;
  beta?: boolean;
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
    key: "providers",
    label: "AI Providers",
    iconElement: (
      <Image
        src={providerFaviconUrl("opencode.ai")}
        alt=""
        width={18}
        height={18}
        className="mr-1 rounded-[4px] object-contain"
        unoptimized
      />
    ),
    href: "/settings/providers",
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
    key: "voice",
    label: "Voices",
    icon: VoiceIdIcon,
    href: "/settings/voice",
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
  {
    key: "skills",
    label: "Skills",
    icon: PuzzleIcon,
    href: "/settings/skills",
  },
  {
    key: "devices",
    label: "Devices",
    icon: ComputerIcon,
    href: "/settings/devices",
    beta: true,
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

/**
 * Settings sections that only make sense when the instance bills — hidden
 * from navigation and redirected away on self-host (billing_enabled=false).
 */
export const BILLING_ONLY_SETTINGS_KEYS = new Set(["subscription", "usage"]);

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
