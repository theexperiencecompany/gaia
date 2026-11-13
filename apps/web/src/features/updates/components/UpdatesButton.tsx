"use client";

import { Badge } from "@heroui/badge";
import { NotificationIcon } from "@icons";
import Link from "next/link";
import { SidebarHeaderButton } from "@/components/layout/headers/SidebarHeaderButton";
import { useUnseenUpdates } from "../hooks/useUnseenUpdates";

export function UpdatesButton() {
  const unseen = useUnseenUpdates();

  return (
    <Link href="/updates">
      <Badge
        color="primary"
        shape="circle"
        size="sm"
        content={unseen > 99 ? "99+" : unseen}
        isInvisible={unseen === 0}
        classNames={{ badge: "pointer-events-none select-none border-0" }}
      >
        <SidebarHeaderButton aria-label="Updates" tooltip="Updates">
          <NotificationIcon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-colors group-hover:text-primary" />
        </SidebarHeaderButton>
      </Badge>
    </Link>
  );
}
