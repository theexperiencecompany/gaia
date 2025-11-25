"use client";

import { Button } from "@heroui/button";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { useEffect, useState } from "react";

import { RaisedButton } from "@/components/ui/raised-button";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import {
  usePricing,
  useUserSubscriptionStatus,
} from "@/features/pricing/hooks/usePricing";
import {
  Calendar03Icon,
  CheckListIcon,
  ConnectIcon,
  MessageMultiple02Icon,
  Target02Icon,
  ZapIcon,
} from "@/icons";
import { posthog } from "@/lib";
import { useRefreshTrigger } from "@/stores/notificationStore";
import { NotificationStatus } from "@/types/features/notificationTypes";

export default function SidebarTopButtons() {
  const pathname = usePathname();
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const { plans } = usePricing();
  const refreshTrigger = useRefreshTrigger();
  const { notifications, refetch } = useNotifications({
    status: NotificationStatus.DELIVERED,
    limit: 50,
  });

  const [unreadCount, setUnreadCount] = useState(0);

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
      {!subscriptionStatus?.is_subscribed && (
        <Link href="/pricing">
          <div className="m-1 mb-2 flex h-fit w-fit flex-col justify-center gap-1 rounded-2xl border border-zinc-700 bg-zinc-800 p-3 transition hover:bg-zinc-700 active:scale-95">
            <div className="font-medium">Go on, You Deserve This</div>
            <p className="text-xs text-zinc-400">
              Unlock near-unlimited usage and priority support for ${price} a
              month
            </p>

            <RaisedButton
              className="mt-1 w-full rounded-xl! text-black!"
              color="#00bbff"
              size={"sm"}
            >
              <ZapIcon fill="black" width={17} height={17} />
              Upgrade to Pro
            </RaisedButton>
          </div>
        </Link>
      )}

      <div className="flex w-full flex-col gap-0.5">
        {buttonData.map(({ route, icon, label }) => (
          <div key={route + label} className="relative">
            <Button
              size="sm"
              variant="light"
              color={isRouteActive(route) ? "primary" : "default"}
              className={`group-topbtns w-full justify-start text-sm ${
                isRouteActive(route)
                  ? "text-primary"
                  : "text-zinc-400 hover:text-white"
              }`}
              as={Link}
              href={route}
              onPress={() => {
                posthog.capture("navigation:sidebar_clicked", {
                  destination: route,
                  label,
                });
              }}
            >
              <div className="flex w-full items-center gap-2">
                <div className="flex w-[17px] min-w-[17px] items-center justify-center">
                  <span className="group-topbtns-hover:text-white text-xs">
                    {React.cloneElement(icon, {
                      // color: isRouteActive(route)
                      //   ? "#00bbff"
                      //   : "#9b9b9b",
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
            {route === "/notifications" && unreadCount > 0 && (
              <div className="absolute top-0 right-2 flex h-full items-center justify-center">
                <div className="flex aspect-square h-4 w-4 items-center justify-center rounded-full bg-primary text-xs font-medium text-zinc-950">
                  {unreadCount > 99 ? "9+" : unreadCount}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/*
      <div className="mb-3 px-1">
        <Separator className="bg-zinc-800" />
      </div> */}
    </div>
  );
}
