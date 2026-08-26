"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { usePathname, useRouter } from "next/navigation";

import {
  BILLING_ONLY_SETTINGS_KEYS,
  DESKTOP_ONLY_SETTINGS_KEYS,
  settingsPageItems,
} from "@/features/settings/config/settingsConfig";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";
import { useElectron } from "@/hooks/useElectron";

export default function SettingsSidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const { isElectron } = useElectron();
  const { data: setupStatus } = useSetupStatus();

  // Self-host instances have no billing — the entries make no sense there.
  const billingHidden = setupStatus?.billing_enabled === false;

  const visibleItems = settingsPageItems.filter(
    (item) =>
      (isElectron || !DESKTOP_ONLY_SETTINGS_KEYS.has(item.key)) &&
      !(billingHidden && BILLING_ONLY_SETTINGS_KEYS.has(item.key)),
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

          return (
            <Button
              key={item.key}
              onPress={() => item.href && handleNavigation(item.href)}
              size="sm"
              variant={isActive ? "flat" : "light"}
              color={isActive ? "primary" : "default"}
              className={`group ${isActive ? "text-primary" : "text-zinc-400 hover:text-white"} flex w-full justify-start`}
            >
              {item.iconElement ??
                (Icon && (
                  <Icon
                    className="mr-1 h-5 w-5 transition-colors"
                    color="currentColor"
                  />
                ))}
              <span className="text-sm">{item.label}</span>
              {item.beta && (
                <Chip size="sm" variant="flat" color="success">
                  Beta
                </Chip>
              )}
            </Button>
          );
        })}
      </nav>
    </div>
  );
}
