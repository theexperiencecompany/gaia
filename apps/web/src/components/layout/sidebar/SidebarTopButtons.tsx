"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { useEffect, useState } from "react";

import {
  getNavigationShortcut,
  ShortcutKeysDisplay,
} from "@/config/keyboardShortcuts";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import {
  usePricing,
  useUserSubscriptionStatus,
} from "@/features/pricing/hooks/usePricing";
import {
  Calendar03Icon,
  CheckListIcon,
  ConnectIcon,
  DashboardSquare02Icon,
  MessageMultiple02Icon,
  Target02Icon,
  ZapIcon,
} from "@/icons";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useRefreshTrigger } from "@/stores/notificationStore";
import { NotificationStatus } from "@/types/features/notificationTypes";
import { SidebarPromo } from "./SidebarPromo";

export default function SidebarTopButtons() {
  const pathname = usePathname();
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const { plans } = usePricing();
  const refreshTrigger = useRefreshTrigger();
  const [unreadCount, setUnreadCount] = useState(0);
  const { notifications, refetch } = useNotifications({
    status: NotificationStatus.DELIVERED,
    limit: 50,
  });

  const monthlyPlan = plans.find(
    (p) => p.name === "Pro" && p.duration === "monthly",
  );
  const price = monthlyPlan ? monthlyPlan.amount / 100 : 15;

  useEffect(() => {
    refetch();
  }, [refreshTrigger, refetch]);

  useEffect(() => {
    setUnreadCount(
      notifications.filter((n) => n.status !== NotificationStatus.READ).length,
    );
  }, [notifications]);

  const isRouteActive = (route: string) => {
    if (route === "/c") {
      return pathname === "/c" || pathname.startsWith("/c/");
    }
    return pathname === route;
  };

  const buttonData = [
    {
      route: "/dashboard",
      icon: <DashboardSquare02Icon />,
      label: "Dashboard",
    },
    {
      route: "/calendar",
      icon: <Calendar03Icon />,
      label: "Calendar",
    },
    {
      route: "/goals",
      icon: <Target02Icon />,
      label: "Goals",
    },
    {
      route: "/todos",
      icon: <CheckListIcon />,
      label: "Todos",
    },
    {
      route: "/integrations",
      icon: <ConnectIcon />,
      label: "Integrations",
    },
    // {
    //   route: "/mail",
    //   icon: <Mail01Icon />,
    //   label: "Mail",
    // },
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

    // {
    //   route: "/browser",
    //   icon: <AiBrowserIcon height={23} width={23} />,
    //   label: "Use Browser",
    // },
  ];

  return (
    <div className="flex flex-col">
      {/* Only show Upgrade to Pro button when user doesn't have an active subscription */}
      {!subscriptionStatus?.is_subscribed && <SidebarPromo price={price} />}

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
                  className={`group-topbtns focus-visible:outline-none w-full justify-start text-sm ${
                    isRouteActive(route)
                      ? "text-zinc-300"
                      : "text-zinc-400 hover:text-zinc-300"
                  }`}
                  as={Link}
                  href={route}
                  onPress={() => {
                    trackEvent(ANALYTICS_EVENTS.NAVIGATION_SIDEBAR_CLICKED, {
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
              {route === "/notifications" && unreadCount > 0 && (
                <div className="absolute top-0 right-2 flex h-full items-center justify-center">
                  <div className="flex aspect-square h-4 w-4 items-center justify-center rounded-full bg-primary text-xs font-medium text-zinc-950">
                    {unreadCount > 99 ? "9+" : unreadCount}
                  </div>
                </div>
              )}
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
