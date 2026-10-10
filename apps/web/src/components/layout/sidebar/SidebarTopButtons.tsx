"use client";

import type { EventProperties } from "@gaia/shared/analytics/events";
import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import {
  // Calendar03Icon, // Temporarily disabled
  CheckListIcon,
  ConnectIcon,
  Home11Icon,
  MessageMultiple02Icon,
  ZapIcon,
} from "@icons";
import Link from "next/link";
import React from "react";
import { ChevronLeft } from "@/components/shared/icons";
import { ShortcutKeysDisplay } from "@/config/keyboardShortcuts";
import { getNavigationShortcut } from "@/config/keyboardShortcutsData";
import { paywallCopyFor } from "@/features/pricing/constants";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { useProMonthlyPlan } from "@/features/pricing/hooks/useProMonthlyPlan";
import { toMajorUnits } from "@/features/pricing/utils/money";
import { usePathname } from "@/i18n/navigation";
import { track } from "@/lib/analytics";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";
import { SidebarPromo } from "./SidebarPromo";

type SidebarNavigation = EventProperties["navigation:sidebar_clicked"];

interface SidebarButton {
  route: SidebarNavigation["destination"];
  icon: React.JSX.Element;
  label: SidebarNavigation["label"];
}

const buttonData: SidebarButton[] = [
  {
    route: "/dashboard",
    icon: <Home11Icon />,
    label: "Home",
  },
  {
    route: "/todos",
    icon: <CheckListIcon />,
    label: "Tasks",
  },
  {
    route: "/integrations",
    icon: <ConnectIcon />,
    label: "Integrations",
  },
  {
    route: "/workflows",
    icon: <ZapIcon />,
    label: "Workflows",
  },
  {
    route: "/c",
    icon: <MessageMultiple02Icon />,
    label: "Chats",
  },
];

export default function SidebarTopButtons() {
  const pathname = usePathname();
  const { isPaid, isUnknown, hasEverSubscribed } = useIsPaid();
  const { plan: monthlyPlan, isLoading: isPriceLoading } = useProMonthlyPlan();
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);

  const price = monthlyPlan
    ? toMajorUnits(monthlyPlan.amount, monthlyPlan.currency)
    : null;

  // In settings, the app nav is noise — a single "Back to chats" is all you need.
  if (pathname.startsWith("/settings")) {
    return (
      <Button
        as={Link}
        href="/c"
        size="sm"
        variant="light"
        className="w-full justify-start gap-2 text-sm text-zinc-400 hover:text-zinc-300"
        startContent={<ChevronLeft className="size-4" />}
      >
        Back to chats
      </Button>
    );
  }

  const isRouteActive = (route: string) => {
    if (route === "/c") {
      return pathname === "/c" || pathname.startsWith("/c/");
    }
    return pathname === route;
  };

  return (
    <div className="flex flex-col">
      {/* Only show Upgrade to Pro button when the plan is known and the user
          doesn't have an active subscription — never while unknown, or a
          paying user on a cold cache briefly sees the free-tier promo. */}
      {!isUnknown && !isPaid && (
        <SidebarPromo
          price={price}
          isPriceLoading={isPriceLoading}
          copy={paywallCopyFor(hasEverSubscribed)}
          onUpgrade={() =>
            openUpgradeModal(undefined, {
              dismissible: true,
              source: "sidebar",
            })
          }
        />
      )}

      <div className="flex w-full flex-col gap-0.5">
        {buttonData.map(({ route, icon, label }) => {
          const shortcut = getNavigationShortcut(route);

          return (
            <div key={route + label} className="relative">
              <Tooltip
                className="rounded-xl"
                showArrow
                content={
                  shortcut ? (
                    <span className="flex items-center gap-2 text-sm text-zinc-400 font-light py-1 px-2">
                      <span className="text-xs">Go to {label}</span>
                      <ShortcutKeysDisplay keys={shortcut.keys} />
                    </span>
                  ) : (
                    label
                  )
                }
                offset={1}
                placement="right"
                delay={0}
                closeDelay={0}
              >
                <Button
                  size="sm"
                  variant={isRouteActive(route) ? "flat" : "light"}
                  // color={isRouteActive(route) ? "primary" : "default"}
                  color={"default"}
                  className={`group-topbtns focus-visible:outline-none w-full justify-start text-sm ${isRouteActive(route) ? "text-zinc-300" : "text-zinc-400 hover:text-zinc-300"}`}
                  as={Link}
                  href={route}
                  onPress={() => {
                    track("navigation:sidebar_clicked", {
                      destination: route,
                      label,
                    });
                  }}
                >
                  <div className="flex w-full items-center gap-2">
                    <div className="flex w-[17px] min-w-[17px] items-center justify-center">
                      <span className="group-topbtns-hover:text-white text-xs">
                        {React.cloneElement(icon, {
                          width: 18,
                          height: 18,
                        })}
                      </span>
                    </div>
                    <span className="w-[calc(100%-45px)] max-w-[200px] truncate text-left">
                      {label}
                    </span>
                  </div>
                </Button>
              </Tooltip>
            </div>
          );
        })}
      </div>

      {/*
      <div className="mb-3 px-1">
        <Separator className="bg-zinc-800" />
      </div> */}
    </div>
  );
}
