"use client";

import Link from "next/link";

import { SidebarHeaderButton } from "@/components/layout/headers/HeaderManager";
import { ChatBubbleAddIcon, Target02Icon } from "@/components/shared/icons";
import { NotificationCenter } from "@/features/notification/components/NotificationCenter";

export default function GoalsHeader() {
  return (
    <div className="flex w-full items-center justify-between">
      <div className="flex items-center gap-2 pl-2 text-zinc-500">
        <Target02Icon width={20} height={20} color={undefined} />
        <span>Goals</span>
      </div>

      <div className="relative z-[100] flex items-center">
        <Link href={"/c"}>
          <SidebarHeaderButton
            aria-label="Create new chat"
            tooltip="Create new chat"
          >
            <ChatBubbleAddIcon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-all group-hover:text-primary" />
          </SidebarHeaderButton>
        </Link>
        <NotificationCenter />
      </div>
    </div>
  );
}
