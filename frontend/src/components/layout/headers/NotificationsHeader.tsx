"use client";

import { Button } from "@heroui/button";
import { Tab, Tabs } from "@heroui/tabs";

import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { NotificationIcon } from "@/components/shared/icons";

interface NotificationsHeaderProps {
  selectedTab: string;
  onTabChange: (key: string) => void;
  unreadCount: number;
  onMarkAllAsRead: () => void;
}

export default function NotificationsHeader({
  selectedTab,
  onTabChange,
  unreadCount,
  onMarkAllAsRead,
}: NotificationsHeaderProps) {
  return (
    <div className="flex w-full items-center justify-between">
      <div className="flex w-full items-center justify-between">
        <HeaderTitle
          icon={<NotificationIcon width={20} height={20} color={undefined} />}
          text="Notifications"
        />

        <div className="relative ml-auto flex items-center pr-1">
          {unreadCount > 0 && (
            <Button variant="flat" onPress={onMarkAllAsRead}>
              Mark All as Read
            </Button>
          )}
        </div>

        <Tabs
          aria-label="Notifications"
          selectedKey={selectedTab}
          onSelectionChange={(key) => onTabChange(key as string)}
        >
          <Tab
            key="unread"
            title={
              <div className="flex items-center gap-2">
                <span>Unread</span>
                {unreadCount > 0 && (
                  <span className="ml-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-primary/10 px-1.5 text-xs font-semibold text-primary">
                    {unreadCount > 99 ? "99+" : unreadCount}
                  </span>
                )}
              </div>
            }
          />
          <Tab key="all" title="All" />
        </Tabs>
      </div>
    </div>
  );
}
