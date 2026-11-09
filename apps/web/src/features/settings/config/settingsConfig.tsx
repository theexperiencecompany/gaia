import {
  AiWebBrowsingIcon,
  Brain02Icon,
  ChartLineData02Icon,
  ComputerIcon,
  CreditCardIcon,
  DiscordIcon,
  LabsIcon,
  Link04Icon,
  MessageMultiple02Icon,
  NoteEditIcon,
  NotificationIcon,
  PlugSocketIcon,
  PuzzleIcon,
  UserCircleIcon,
  UserGroupIcon,
  VoiceIdIcon,
  WhatsappIcon,
} from "@icons";
import type { InstanceRole } from "@shared/api/generated";
import Image from "next/image";
import type { ReactNode } from "react";
import { PostageStampIcon } from "@/components/shared/icons";
import { COMPOSIO_SETUP_PATH } from "@/features/settings/api/composioSetupApi";
import { PROVIDERS_SETTINGS_PATH } from "@/features/settings/components/providers/providerRows";

/** The Providers & Tools entry's mark: the custom lane's gateway logo, before any catalog loads. */
const PROVIDERS_MENU_ICON_URL =
  "https://www.google.com/s2/favicons?domain=opencode.ai&sz=128";

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
  isNew?: boolean;
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
    label: "Providers & Tools",
    iconElement: (
      <Image
        src={PROVIDERS_MENU_ICON_URL}
        alt=""
        width={18}
        height={18}
        className="mr-1 rounded-[4px] object-contain"
        unoptimized
      />
    ),
    href: PROVIDERS_SETTINGS_PATH,
  },
  {
    key: "integrations-setup",
    label: "Integrations setup",
    icon: PlugSocketIcon,
    href: COMPOSIO_SETUP_PATH,
  },
  {
    key: "members",
    label: "Members",
    icon: UserGroupIcon,
    href: "/settings/members",
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
    isNew: true,
  },
  {
    key: "browser",
    label: "Browser",
    icon: AiWebBrowsingIcon,
    href: "/settings/browser",
    isNew: true,
  },
  {
    key: "experimental",
    label: "Experimental",
    icon: LabsIcon,
    href: "/settings/experimental",
    isNew: true,
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
 * from navigation and redirected away on self-host (deployment.bills=false).
 */
export const BILLING_ONLY_SETTINGS_KEYS = new Set(["subscription", "usage"]);

/**
 * Sections that configure the instance itself (its people, model keys and
 * integration project). Only a self-host instance admin has them; hosted
 * accounts carry no role, so they never see these.
 */
const INSTANCE_ADMIN_SETTINGS_KEYS = new Set([
  "members",
  "providers",
  "integrations-setup",
]);

/** Whether an account with this instance role may open a settings section. */
export function isSettingsSectionAllowed(
  key: string,
  role: InstanceRole | undefined,
): boolean {
  return !INSTANCE_ADMIN_SETTINGS_KEYS.has(key) || role === "admin";
}

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
