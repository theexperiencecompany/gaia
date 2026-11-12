"use client";

import { Button, Chip } from "@heroui/react";
import { usePathname, useRouter } from "next/navigation";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import {
  BILLING_ONLY_SETTINGS_KEYS,
  DESKTOP_ONLY_SETTINGS_KEYS,
  isSettingsSectionAllowed,
  settingsPageItems,
} from "@/features/settings/config/settingsConfig";
import { useDeployment } from "@/features/settings/hooks/useSetupStatus";
import { useElectron } from "@/hooks/useElectron";

export default function SettingsSidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const { isElectron } = useElectron();

  // Self-host instances have no billing — the entries make no sense there.
  const billingHidden = !useDeployment().bills;
  const { role } = useCurrentUser();

  const visibleItems = settingsPageItems.filter(
    (item) =>
      (isElectron || !DESKTOP_ONLY_SETTINGS_KEYS.has(item.key)) &&
      !(billingHidden && BILLING_ONLY_SETTINGS_KEYS.has(item.key)) &&
      isSettingsSectionAllowed(item.key, role),
  );

  const handleNavigation = (href: string) => {
    router.push(href);
  };

  return (
    <div className="flex h-full max-w-[280px] flex-col border-t-1 border-zinc-800 pt-3">
      <nav className="flex-1 space-y-1">
        {visibleItems.map((item) => {
          // Match the section itself or any sub-route of it (e.g. the pairing
          // page under /settings/devices). `endsWith` rather than `startsWith`
          // because a non-default locale prefixes the path.
          const isActive = item.href
            ? pathname.endsWith(item.href) || pathname.includes(`${item.href}/`)
            : false;
          const Icon = item.icon;

          const label = (
            <>
              {item.iconElement ??
                (Icon && (
                  <Icon
                    className="mr-1 h-5 w-5 transition-colors"
                    color="currentColor"
                  />
                ))}
              <span className="text-sm">{item.label}</span>
              {item.isNew && (
                <Chip size="sm" variant="soft" color="success">
                  New
                </Chip>
              )}
            </>
          );
          const navigate = () => item.href && handleNavigation(item.href);

          return isActive ? (
            <GaiaButton
              key={item.key}
              onPress={navigate}
              size="sm"
              variant="accent-soft"
              className="group flex w-full justify-start text-primary"
            >
              {label}
            </GaiaButton>
          ) : (
            <Button
              key={item.key}
              onPress={navigate}
              size="sm"
              variant="ghost"
              className="group flex w-full justify-start text-zinc-400 hover:text-white"
            >
              {label}
            </Button>
          );
        })}
      </nav>
    </div>
  );
}
