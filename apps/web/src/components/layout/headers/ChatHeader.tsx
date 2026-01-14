"use client";

import { Kbd } from "@heroui/kbd";
import Link from "next/link";

import { SidebarHeaderButton } from "@/components";
import ModelPickerButton from "@/features/chat/components/composer/ModelPickerButton";
import { NotificationCenter } from "@/features/notification/components/NotificationCenter";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { BubbleChatAddIcon, PinIcon, SearchIcon } from "@/icons";

export default function ChatHeader() {
  const { isMac, modifierKeyName } = usePlatform();

  // Command menu is now handled globally in the layout
  // Just trigger it to open via the global keyboard shortcut
  const handleSearchClick = () => {
    // Dispatch a keyboard event to trigger the command menu
    const event = new KeyboardEvent("keydown", {
      key: "k",
      metaKey: isMac,
      ctrlKey: !isMac,
      bubbles: true,
    });
    document.dispatchEvent(event);
  };

  return (
    <div className="flex w-full justify-between">
      <ModelPickerButton />
      <div className="relative flex items-center">
        <SidebarHeaderButton
          onClick={handleSearchClick}
          aria-label="Search"
          tooltip={
            <div className="flex items-center gap-2">
              Search
              <Kbd keys={[modifierKeyName]}> K</Kbd>
            </div>
          }
        >
          <SearchIcon className="max-h-5 min-h-5 max-w-5 min-w-5 text-foreground-400 group-hover:text-primary" />
        </SidebarHeaderButton>
        <Link href={"/pins"}>
          <SidebarHeaderButton
            aria-label="Pinned Messages"
            tooltip="Pinned Messages"
          >
            <PinIcon className="min-h-[20px] min-w-[20px] text-foreground-400 transition-all group-hover:text-primary" />
          </SidebarHeaderButton>
        </Link>
        <Link href={"/c"}>
          <SidebarHeaderButton
            aria-label="Create new chat"
            tooltip="Create new chat"
          >
            <BubbleChatAddIcon className="min-h-[20px] min-w-[20px] text-foreground-400 transition-all group-hover:text-primary" />
          </SidebarHeaderButton>
        </Link>
        <NotificationCenter />
      </div>
    </div>
  );
}
