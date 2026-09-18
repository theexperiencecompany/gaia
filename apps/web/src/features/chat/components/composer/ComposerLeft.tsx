import { Button } from "@heroui/button";
import { Kbd } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";
import { AttachmentIcon, PlusSignIcon, Tick02Icon, ToolsIcon } from "@icons";
import React from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { useIsInitialResponseStreaming } from "@/stores/streamStore";
import type { ComposerMode } from "@/types/shared/searchTypes";

interface SearchbarLeftDropdownProps {
  selectedMode: Set<ComposerMode>;
  openFilePicker: () => void;
  handleSelectionChange: (mode: ComposerMode) => void;
  onOpenSlashCommandDropdown?: () => void;
  isSlashCommandDropdownOpen?: boolean;
}

interface DropdownItemConfig {
  id: ComposerMode;
  label: string;
  icon: React.ReactNode;
  action?: () => void;
  isMode?: boolean;
  loadingText?: string;
  description?: string;
}

export default function ComposerLeft({
  selectedMode,
  openFilePicker,
  handleSelectionChange,
  onOpenSlashCommandDropdown,
  isSlashCommandDropdownOpen,
}: SearchbarLeftDropdownProps) {
  // Locked only during the initial response (send → main_response_complete),
  // matching the send button — unlocks once the agent acknowledges the task.
  const isMainResponseStreaming = useIsInitialResponseStreaming();
  const currentMode = React.useMemo(
    () => Array.from(selectedMode)[0],
    [selectedMode],
  );

  const dropdownItems: DropdownItemConfig[] = [
    {
      id: "upload_file",
      label: "Attach Files",
      icon: (
        <AttachmentIcon className="min-h-[20px] min-w-[20px] text-primary" />
      ),
      action: openFilePicker,
      isMode: false,
      description: "Upload and analyze documents, images or other files",
    },
  ];

  return (
    <div className="flex items-center gap-2">
      {/* Add Context Dropdown */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            isIconOnly
            radius="full"
            variant="flat"
            className={cn(
              "group relative h-9 w-9",
              isMainResponseStreaming ? "cursor-wait!" : "",
            )}
            isDisabled={isMainResponseStreaming}
          >
            <PlusSignIcon className="min-h-[23px] min-w-[23px] text-zinc-400!" />
            <span
              className={`absolute -top-0 -right-0 h-2 w-2 rounded-full bg-primary transition ${currentMode ? "opacity-100" : "opacity-0"}`}
              aria-hidden="true"
            />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" side="top" className="w-fit">
          {dropdownItems.map((item) => (
            <Tooltip
              content={<div className="max-w-[270px]">{item.description}</div>}
              key={item.id}
              color="foreground"
              radius="sm"
            >
              <DropdownMenuItem
                key={item.id}
                onClick={() => {
                  trackEvent(ANALYTICS_EVENTS.CHAT_COMPOSER_PLUS_MENU_CLICKED, {
                    item_id: item.id,
                    item_label: item.label,
                    is_mode: item.isMode,
                  });
                  // setLoadingText(item.loadingText ?? "");
                  if (item.isMode)
                    handleSelectionChange(item.id as ComposerMode);
                  else if (item.action) item.action();
                }}
                className="cursor-pointer"
              >
                <div
                  className={cn(
                    "flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2",
                    currentMode === item.id ? "bg-primary/30 text-primary" : "",
                  )}
                >
                  <div className="flex flex-col">
                    <div className="flex flex-row items-center gap-2">
                      {item.icon}
                      <span className="">{item.label}</span>
                    </div>
                  </div>
                  <div>
                    {currentMode === item.id && (
                      <Tick02Icon className="min-h-[20px] min-w-[20px] text-primary" />
                    )}
                  </div>
                </div>
              </DropdownMenuItem>
            </Tooltip>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Tools Button */}
      {onOpenSlashCommandDropdown && (
        <Tooltip
          content={
            <div className="flex items-center gap-2">
              Browse all tools
              <Kbd className="text-zinc-400">Press /</Kbd>
            </div>
          }
          placement="right"
          showArrow
        >
          <Button
            isIconOnly
            radius="full"
            variant="flat"
            color={isSlashCommandDropdownOpen ? "primary" : "default"}
            className={cn(
              "group relative flex h-9 w-9 items-center justify-center",
              isMainResponseStreaming ? "cursor-wait!" : "",
            )}
            isDisabled={isMainResponseStreaming}
            onClick={() => {
              trackEvent(ANALYTICS_EVENTS.CHAT_TOOLS_BUTTON_CLICKED, {
                is_open: isSlashCommandDropdownOpen,
              });
              onOpenSlashCommandDropdown?.();
            }}
          >
            <ToolsIcon
              className="min-h-[23px] min-w-[23px]"
              width={30}
              height={30}
            />
            {isSlashCommandDropdownOpen && (
              <span
                className="absolute top-0 right-0 h-2 w-2 rounded-full bg-primary transition"
                aria-hidden="true"
              />
            )}
          </Button>
        </Tooltip>
      )}
    </div>
  );
}
