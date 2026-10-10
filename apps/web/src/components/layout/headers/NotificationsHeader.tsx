"use client";

import { Button } from "@heroui/button";
import { Tab, Tabs } from "@heroui/tabs";
import { NotificationIcon } from "@icons";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";

interface NotificationsHeaderProps {
  selectedTab: string;
  onTabChange: (key: string) => void;
  unreadCount: number;
  /** Whether the mark-all-read button should show. Separate from `unreadCount`
   * because the loaded count can undercount when the store hit its page cap. */
  showMarkAllAsRead: boolean;
  onMarkAllAsRead: () => void;
}

export default function NotificationsHeader({
  selectedTab,
  onTabChange,
  unreadCount,
  showMarkAllAsRead,
  onMarkAllAsRead,
}: NotificationsHeaderProps) {
  return (
    <div className="flex w-full items-center justify-between gap-4">
      <HeaderTitle
        icon={<NotificationIcon width={20} height={20} />}
        text="Notifications"
      />

      <div className="flex items-center gap-3">
        <Tabs
          aria-label="Notifications"
          selectedKey={selectedTab}
          onSelectionChange={(key) => onTabChange(key as string)}
          variant="underlined"
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

        {showMarkAllAsRead && (
          <Button variant="flat" size="sm" onPress={onMarkAllAsRead}>
            Mark All as Read
          </Button>
        )}
      </div>
    </div>
  );
}
