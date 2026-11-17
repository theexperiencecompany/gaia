import {
  BookOpen02Icon,
  CircleArrowUp02Icon,
  CloudDownloadIcon,
  CustomerService01Icon,
  KeyboardIcon,
  Logout02Icon,
  PackageOpenIcon,
  Settings01Icon,
} from "@icons";
import { useRouter } from "next/navigation";
import type { ComponentType, ReactNode } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { useDeployment } from "@/features/settings/hooks/useSetupStatus";
import { useReleases } from "@/features/whats-new/hooks/useReleases";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";
import {
  BILLING_ONLY_SETTINGS_KEYS,
  isSettingsSectionAllowed,
  settingsPageItems,
  socialMediaItems,
} from "../config/settingsConfig";

export interface SettingsMenuItem {
  key: string;
  label: string;
  icon?: ComponentType<{ className?: string; color?: string }>;
  /** Pre-rendered brand mark for entries without an @icons glyph (e.g. favicons). */
  iconElement?: ReactNode;
  href?: string;
  action?: () => void;
  color?: "danger" | "default";
  external?: boolean;
  hasSubmenu?: boolean;
  iconColor?: string;
  badge?: ReactNode;
  customClassNames?: {
    title?: string;
  };
}

interface SettingsMenuSectionsOptions {
  onOpenShortcuts: () => void;
  onSignOut: () => void;
  downloadLabel: string;
}

/** The settings menu's sections for this user: plan, role and deployment decide which entries show. */
export function useSettingsMenuSections({
  onOpenShortcuts,
  onSignOut,
  downloadLabel,
}: SettingsMenuSectionsOptions): {
  id: string;
  title: string | undefined;
  showDivider: boolean;
  items: SettingsMenuItem[];
}[] {
  const router = useRouter();
  const { isPaid, isUnknown } = useIsPaid();
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);
  // Self-host instances have no billing — the entries make no sense there.
  const deployment = useDeployment();
  const billingHidden = !deployment.bills;
  const selfHosted = deployment.kind === "selfhost";
  const { role } = useCurrentUser();
  const { unseen: unseenReleases } = useReleases();

  // Entries surfaced directly in this menu; billing-only ones drop out on self-host.
  const quickSettingsKeys = new Set(
    ["memory", "linked-accounts", "providers", "usage"].filter(
      (key) => !(billingHidden && BILLING_ONLY_SETTINGS_KEYS.has(key)),
    ),
  );

  return [
    // Never show the upgrade item while the plan is unknown — a cold-cache
    // paying user would otherwise see an "Upgrade to Pro" entry on reload —
    // nor on self-host, where billing does not exist at all.
    ...(isUnknown || isPaid || billingHidden
      ? []
      : [
          {
            id: "upgrade",
            title: undefined,
            showDivider: true,
            items: [
              {
                key: "upgrade_to_pro",
                label: "Subscribe to GAIA Pro",
                action: () =>
                  openUpgradeModal(undefined, {
                    dismissible: true,
                    source: "settings_menu",
                  }),
                icon: CircleArrowUp02Icon,
                iconColor: "#00bbff",
                customClassNames: { title: "text-accent font-medium" },
              },
            ],
          },
        ]),
    {
      id: "shortcuts",
      title: undefined,
      showDivider: true,
      items: [
        ...settingsPageItems.filter(
          (item) =>
            quickSettingsKeys.has(item.key) &&
            isSettingsSectionAllowed(item.key, role),
        ),
        {
          key: "keyboard_shortcuts",
          label: "Keyboard Shortcuts",
          icon: KeyboardIcon,
          action: onOpenShortcuts,
        },
      ],
    },
    {
      id: "community",
      title: "Community",
      showDivider: true,
      items: socialMediaItems,
    },
    {
      id: "app",
      title: undefined,
      showDivider: false,
      items: [
        // GAIA's release notes announce the hosted product.
        ...(selfHosted
          ? []
          : [
              {
                key: "whats-new",
                label: "What's new",
                icon: PackageOpenIcon,
                hasSubmenu: true,
                badge:
                  unseenReleases.length > 0 ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                  ) : undefined,
              },
            ]),
        {
          key: "download",
          label: downloadLabel,
          icon: CloudDownloadIcon,
          hasSubmenu: true,
        },
        {
          key: "resources",
          label: "Resources",
          icon: BookOpen02Icon,
          hasSubmenu: true,
        },
        {
          key: "support",
          label: "Support",
          icon: CustomerService01Icon,
          hasSubmenu: true,
        },
        {
          key: "settings",
          label: "Settings",
          icon: Settings01Icon,
          action: () => router.push("/settings"),
        },
        {
          key: "logout",
          label: "Sign Out",
          icon: Logout02Icon,
          color: "danger" as const,
          action: onSignOut,
        },
      ],
    },
  ];
}
