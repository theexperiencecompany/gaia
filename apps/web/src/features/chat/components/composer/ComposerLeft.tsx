import { Kbd, Tooltip } from "@heroui/react";
import { AttachmentIcon, PlusSignIcon, Tick02Icon, ToolsIcon } from "@icons";
import React from "react";
import { Focusable } from "react-aria-components";
import { overlayVariants } from "@/components/shared/controlVariants";
import { shapeVariants } from "@/components/shared/shape";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ATTACHMENT_LIMITS_HINT } from "@/features/chat/constants/files";
import { track } from "@/lib/analytics";
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
  id: NonNullable<ComposerMode>;
  label: string;
  icon: React.ReactNode;
  action?: () => void;
  isMode: boolean;
  loadingText?: string;
  description?: string;
}

export default function ComposerLeft({
  selectedMode,
  openFilePicker,
  handleSelectionChange,
  onOpenSlashCommandDropdown,
  isSlashCommandDropdownOpen = false,
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
        <AttachmentIcon className="min-h-[20px] min-w-[20px] text-accent" />
      ),
      action: openFilePicker,
      isMode: false,
      description: ATTACHMENT_LIMITS_HINT,
    },
  ];

  return (
    <div className="flex items-center gap-2">
      {/* Add Context Dropdown */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="icon"
            className={cn(
              "group relative h-9 w-9 rounded-full border-none bg-zinc-700 p-0 hover:bg-zinc-600/90",
              isMainResponseStreaming ? "cursor-wait!" : "",
            )}
            disabled={isMainResponseStreaming}
          >
            <PlusSignIcon className="min-h-[23px] min-w-[23px] text-zinc-400!" />
            <span
              className={`absolute -top-0 -right-0 h-2 w-2 rounded-full bg-accent transition ${currentMode ? "opacity-100" : "opacity-0"}`}
              aria-hidden="true"
            />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          side="top"
          className="w-fit gap-2 rounded-xl border-none bg-zinc-900 p-1 text-white outline-2! outline-zinc-800!"
        >
          {dropdownItems.map((item) => (
            <Tooltip key={item.id}>
              <Tooltip.Trigger>
                <DropdownMenuItem
                  key={item.id}
                  onClick={() => {
                    track("chat:composer_plus_menu_clicked", {
                      item_id: item.id,
                      is_mode: item.isMode,
                    });
                    // setLoadingText(item.loadingText ?? "");
                    if (item.isMode)
                      handleSelectionChange(item.id as ComposerMode);
                    else if (item.action) item.action();
                  }}
                  className={cn(
                    "cursor-pointer rounded-lg px-3 py-2",
                    currentMode === item.id
                      ? "bg-[#00bbff50] text-accent focus:bg-[#00bbff50] focus:text-accent"
                      : "focus:bg-zinc-800 focus:text-white",
                  )}
                >
                  <div className="flex w-full items-center justify-between gap-3">
                    <div className="flex flex-col">
                      <div className="flex flex-row items-center gap-2">
                        {item.icon}
                        <span className="">{item.label}</span>
                      </div>
                    </div>
                    <div>
                      {currentMode === item.id && (
                        <Tick02Icon className="min-h-[20px] min-w-[20px] text-accent" />
                      )}
                    </div>
                  </div>
                </DropdownMenuItem>
              </Tooltip.Trigger>
              <Tooltip.Content
                className={overlayVariants({
                  surface: "foreground",
                  className: shapeVariants({ shape: "sm" }),
                })}
              >
                <div className="max-w-[270px]">{item.description}</div>
              </Tooltip.Content>
            </Tooltip>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Tools Button */}
      {onOpenSlashCommandDropdown && (
        <Tooltip>
          <Focusable>
            <Button
              size="icon"
              className={cn(
                "group relative flex h-9 w-9 items-center justify-center rounded-full border-none bg-zinc-700 fill-zinc-400 p-0 text-zinc-400 hover:bg-zinc-600/90",
                isMainResponseStreaming ? "cursor-wait!" : "",
                isSlashCommandDropdownOpen &&
                  "border-accent/50 bg-accent/20 text-accent hover:bg-accent/40",
              )}
              disabled={isMainResponseStreaming}
              onClick={() => {
                track("chat:tools_button_clicked", {
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
                  className="absolute top-0 right-0 h-2 w-2 rounded-full bg-accent transition"
                  aria-hidden="true"
                />
              )}
            </Button>
          </Focusable>
          <Tooltip.Content placement="right" showArrow>
            <div className="flex items-center gap-2">
              Browse all tools
              <Kbd>Press /</Kbd>
            </div>
          </Tooltip.Content>
        </Tooltip>
      )}
    </div>
  );
}
