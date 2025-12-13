"use client";

import { Button } from "@heroui/button";
import { useRouter, useSearchParams } from "next/navigation";

import { settingsPageItems } from "@/features/settings/config/settingsConfig";

export default function SettingsSidebar() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const currentSection = searchParams.get("section") || "general";

  const handleNavigation = (href: string) => {
    router.push(href);
  };

  return (
    <div className="flex h-full max-w-[280px] flex-col border-t-1 border-zinc-800 pt-3">
      <nav className="flex-1 space-y-1">
        {settingsPageItems.map((item) => {
          const isActive = currentSection === item.href?.split("section=")[1];
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
              {Icon && (
                <Icon
                  className={`mr-1 h-5 w-5 transition-colors`}
                  color="currentColor"
                />
              )}
              <span className="text-sm">{item.label}</span>
            </Button>
          );
        })}
      </nav>
    </div>
  );
}
