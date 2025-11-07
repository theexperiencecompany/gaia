"use client";

import { Button } from "@heroui/button";
import { BarChart3 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";

import {
  AccountSetting02Icon,
  AiBrain01Icon,
  CreditCardIcon,
  MessageMultiple02Icon,
} from "@/components/shared/icons";

type MenuItem = {
  label: string;
  icon: React.ElementType;
  href: string;
};

export default function SettingsSidebar() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const currentSection = searchParams.get("section") || "general";

  const handleNavigation = (href: string) => {
    router.push(href);
  };

  const settingsMenuItems: MenuItem[] = [
    {
      label: "Account",
      icon: AccountSetting02Icon,
      href: "/settings?section=account",
    },
    {
      label: "Subscription",
      icon: CreditCardIcon,
      href: "/settings?section=subscription",
    },
    {
      label: "Usage",
      icon: BarChart3,
      href: "/settings?section=usage",
    },
    {
      label: "Preferences",
      icon: MessageMultiple02Icon,
      href: "/settings?section=preferences",
    },
    {
      label: "Memory",
      icon: AiBrain01Icon,
      href: "/settings?section=memory",
    },
  ];

  return (
    <div className="flex h-full max-w-[280px] flex-col border-t-1 border-zinc-800 pt-3">
      <nav className="flex-1 space-y-1">
        {settingsMenuItems.map((item) => {
          const isActive = currentSection === item.href.split("section=")[1];
          const Icon = item.icon;

          return (
            <Button
              key={item.href}
              onPress={() => handleNavigation(item.href)}
              size="sm"
              variant={isActive ? "flat" : "light"}
              color={isActive ? "primary" : "default"}
              className={`group ${isActive ? "text-primary" : "text-zinc-400"} flex w-full justify-start`}
            >
              <Icon
                className={`mr-1 h-5 w-5 transition-colors ${isActive ? "text-primary" : "text-zinc-400"}`}
              />
              <span className="text-sm">{item.label}</span>
            </Button>
          );
        })}
      </nav>
    </div>
  );
}
