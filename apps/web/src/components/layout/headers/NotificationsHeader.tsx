"use client";

import { NotificationIcon } from "@icons";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";

export default function NotificationsHeader() {
  return (
    <div className="flex w-full items-center">
      <HeaderTitle
        icon={<NotificationIcon width={20} height={20} />}
        text="Notifications"
      />
    </div>
  );
}
