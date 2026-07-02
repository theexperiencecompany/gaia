"use client";

import { Kbd } from "@heroui/kbd";
import { BubbleChatAddIcon, PinIcon, SearchIcon } from "@icons";
import Link from "next/link";
import { SidebarHeaderButton } from "@/components/layout/headers/HeaderManager";
import ModelSelectorDevControls from "@/components/layout/headers/ModelSelectorDevControls";
import { prepareNewChat } from "@/features/chat/utils/newChatNavigation";
import { preloadCommandMenu } from "@/features/command/CommandMenuProvider";
import { useCommandMenuStore } from "@/features/command/store";
import { NotificationCenter } from "@/features/notification/components/NotificationCenter";
import { usePlatform } from "@/hooks/ui/usePlatform";

export default function ChatHeader() {
  const { modifierKeyName } = usePlatform();
  const openCommandMenu = useCommandMenuStore((s) => s.open);

  return (
    <div className="flex w-full justify-between">
      <div className="relative ml-auto flex items-center">
        <ModelSelectorDevControls />
        <SidebarHeaderButton
          onClick={openCommandMenu}
          onMouseEnter={preloadCommandMenu}
          onFocus={preloadCommandMenu}
          aria-label="Search"
          tooltip={
            <div className="flex items-center gap-2">
              Search
              <Kbd keys={[modifierKeyName]}> K</Kbd>
            </div>
          }
        >
          <SearchIcon className="max-h-5 min-h-5 max-w-5 min-w-5 text-zinc-400 group-hover:text-primary" />
        </SidebarHeaderButton>
        <Link href={"/pins"}>
          <SidebarHeaderButton
            aria-label="Pinned Messages"
            tooltip="Pinned Messages"
          >
            <PinIcon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-all group-hover:text-primary" />
          </SidebarHeaderButton>
        </Link>
        <Link href={"/c"} onClick={prepareNewChat}>
          <SidebarHeaderButton
            aria-label="Create new chat"
            tooltip="Create new chat"
          >
            <BubbleChatAddIcon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-all group-hover:text-primary" />
          </SidebarHeaderButton>
        </Link>
        <NotificationCenter />
      </div>
    </div>
  );
}
