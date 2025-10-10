"use client";

import { Button } from "@heroui/button";
import { CircleArrowUp, ZapIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { useEffect, useState } from "react";

import {
  CalendarIcon,
  CheckmarkCircle02Icon,
  MessageMultiple02Icon,
  NotificationIcon,
  Target04Icon,
} from "@/components/shared/icons";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/shadcn/accordion";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import { useRefreshTrigger } from "@/stores/notificationStore";
import { useMenuAccordion } from "@/stores/uiStore";
import { NotificationStatus } from "@/types/features/notificationTypes";

import { accordionItemStyles } from "./constants";

export default function SidebarTopButtons() {
  const pathname = usePathname();
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const refreshTrigger = useRefreshTrigger();
  const { notifications, refetch } = useNotifications({
    status: NotificationStatus.DELIVERED,
    limit: 50,
  });
  const { isExpanded: isMenuExpanded, setExpanded: setMenuExpanded } =
    useMenuAccordion();

  const [unreadCount, setUnreadCount] = useState(0);

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
      route: "/notifications",
      icon: <NotificationIcon />,
      label: "Notifications",
    },
    {
      route: "/calendar",
      icon: <CalendarIcon />,
      label: "Calendar",
    },
    {
      route: "/goals",
      icon: <Target04Icon />,
      label: "Goals",
    },
    {
      route: "/todos",
      icon: <CheckmarkCircle02Icon />,
      label: "Todos",
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
        <Link href={"/pricing"}>
          <Button
            variant="faded"
            className="mb-2 flex h-fit w-full justify-start gap-3 px-3"
          >
            <CircleArrowUp width={20} height={20} />
            <div className="flex items-center gap-4">
              <div className="flex w-full flex-col justify-center py-2">
                <div className="text-left text-sm font-medium">
                  Upgrade to Pro
                </div>
                <div className="line-clamp-2 text-left text-xs font-light text-wrap text-foreground-500">
                  All features & unlimited usage
                </div>
              </div>
            </div>
          </Button>
        </Link>
      )}

      <div>
        <Accordion
          type="multiple"
          className="w-full p-0"
          defaultValue={isMenuExpanded ? ["menu"] : []}
          onValueChange={(value) => {
            setMenuExpanded(value.includes("menu"));
          }}
        >
          <AccordionItem value="menu" className={accordionItemStyles.item}>
            <AccordionTrigger className={accordionItemStyles.trigger}>
              Menu
            </AccordionTrigger>
            <AccordionContent className={accordionItemStyles.content}>
              <div className="flex w-full flex-col gap-0.5">
                {buttonData.map(({ route, icon, label }, index) => (
                  <div key={index} className="relative">
                    <Button
                      size="sm"
                      variant="light"
                      color={isRouteActive(route) ? "primary" : "default"}
                      className={`w-full justify-start text-sm ${
                        isRouteActive(route) ? "text-primary" : "text-zinc-400"
                      }`}
                      as={Link}
                      href={route}
                    >
                      <div className="flex w-full items-center gap-2">
                        <div className="flex w-[17px] min-w-[17px] items-center justify-center">
                          <span className="text-xs">
                            {React.cloneElement(icon, {
                              color: isRouteActive(route)
                                ? "#00bbff"
                                : "#9b9b9b",
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
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>

      {/*
      <div className="mb-3 px-1">
        <Separator className="bg-zinc-800" />
      </div> */}
    </div>
  );
}
