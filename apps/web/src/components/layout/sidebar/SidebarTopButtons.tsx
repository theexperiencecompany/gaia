"use client";

import type { EventProperties } from "@gaia/shared/analytics/events";
import { Tooltip } from "@heroui/react";
import {
  // Calendar03Icon, // Temporarily disabled
  CheckListIcon,
  ConnectIcon,
  Home11Icon,
  MessageMultiple02Icon,
  ZapIcon,
} from "@icons";
import React from "react";
import { ChevronLeft } from "@/components/shared/icons";
import { LinkButton } from "@/components/shared/LinkButton";
import { ShortcutKeysDisplay } from "@/config/keyboardShortcuts";
import { getNavigationShortcut } from "@/config/keyboardShortcutsData";
import { paywallCopyFor } from "@/features/pricing/constants";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { useProMonthlyPlan } from "@/features/pricing/hooks/useProMonthlyPlan";
import { toMajorUnits } from "@/features/pricing/utils/money";
import { useDeployment } from "@/features/settings/hooks/useSetupStatus";
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
  // Self-host instances have no billing — the promo makes no sense there.
  const billingHidden = !useDeployment().bills;

  const price = monthlyPlan
    ? toMajorUnits(monthlyPlan.amount, monthlyPlan.currency)
    : null;

  // In settings, the app nav is noise — a single "Back to chats" is all you need.
  if (pathname.startsWith("/settings")) {
    return (
      <LinkButton
        href="/c"
        size="sm"
        variant="ghost"
        tone="muted"
        hoverTone="dim"
        className="w-full justify-start gap-2 text-sm"
      >
        <ChevronLeft className="size-4" />
        Back to chats
      </LinkButton>
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
      {/* Only show Upgrade to Pro button when billing is enabled, the plan is
          known and the user doesn't have an active subscription — never while
          unknown, or a paying user on a cold cache briefly sees the free-tier
          promo. Self-host instances have no billing at all. */}
      {!billingHidden && !isUnknown && !isPaid && (
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
              <Tooltip delay={0} closeDelay={0}>
                <LinkButton
                  href={route}
                  size="sm"
                  variant={isRouteActive(route) ? "secondary" : "ghost"}
                  tone={isRouteActive(route) ? "dim" : "muted"}
                  hoverTone={isRouteActive(route) ? "none" : "dim"}
                  className="group-topbtns focus-visible:outline-none w-full justify-start text-sm"
                  onClick={() => {
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
                </LinkButton>
                <Tooltip.Content placement="right" offset={1} showArrow>
                  {shortcut ? (
                    <span className="flex items-center gap-2 text-sm text-zinc-400 font-light py-1 px-2">
                      <span className="text-xs">Go to {label}</span>
                      <ShortcutKeysDisplay keys={shortcut.keys} />
                    </span>
                  ) : (
                    label
                  )}
                </Tooltip.Content>
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
