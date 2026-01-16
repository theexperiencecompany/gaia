import { Kbd } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";
import React from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { AttachmentIcon, PlusSignIcon, Tick02Icon, ToolsIcon } from "@/icons";
import { posthog } from "@/lib/posthog";
import { cn } from "@/lib/utils";
import type { SearchMode } from "@/types/shared";

interface SearchbarLeftDropdownProps {
  selectedMode: Set<SearchMode>;
  openFileUploadModal: () => void;
  handleSelectionChange: (mode: SearchMode) => void;
  onOpenSlashCommandDropdown?: () => void;
  isSlashCommandDropdownOpen?: boolean;
}

interface DropdownItemConfig {
  id: SearchMode;
  label: string;
  icon: React.ReactNode;
  action?: () => void;
  isMode?: boolean;
  loadingText?: string;
  description?: string;
}

export default function ComposerLeft({
  selectedMode,
  openFileUploadModal,
  handleSelectionChange,
  onOpenSlashCommandDropdown,
  isSlashCommandDropdownOpen,
}: SearchbarLeftDropdownProps) {
  const { isLoading } = useLoading();
  // const { setLoadingText } = useLoadingText();

  const currentMode = React.useMemo(
    () => Array.from(selectedMode)[0],
    [selectedMode],
  );

  const dropdownItems: DropdownItemConfig[] = [
    // {
    //   id: "deep_research",
    //   label: "Deep Research",
    //   icon: (
    //     <AiWebBrowsingIcon className="min-h-[20px] min-w-[20px] text-primary" />
    //   ),
    //   isMode: true,
    //   description:
    //     "Search the web and fetch content from those pages, extracting key information",
    // },
    // {
    //   id: "web_search",
    //   label: "Web search",
    //   icon: (
    //     <GlobalSearchIcon className="min-h-[20px] min-w-[20px] text-primary" />
    //   ),
    //   isMode: true,
    //   description: "Search the web for the latest information",
    // },
    // {
    //   id: "fetch_webpage",
    //   label: "Fetch Webpage",
    //   icon: <ArrowUpRight className="min-h-[20px] min-w-[20px] text-primary" />,
    //   action: openPageFetchModal,
    //   isMode: false,
    //   description: "Retrieve and understand content from specific webpages",
    // },
    // {
    //   id: "generate_image",
    //   label: "Generate Image",
    //   icon: <Image02Icon className="min-h-[20px] min-w-[20px] text-primary" />,
    //   action: openGenerateImageModal,
    //   isMode: false,
    //   description: "Create AI-generated images from text",
    // },
    {
      id: "upload_file",
      label: "Attach Files",
      icon: (
        <AttachmentIcon className="min-h-[20px] min-w-[20px] text-primary" />
      ),
      action: openFileUploadModal,
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
            size="icon"
            className={cn(
              "group relative h-9 w-9 rounded-full border-none p-0 transition bg-surface-200 dark:bg-surface-300 hover:bg-surface-300 dark:hover:bg-surface-400 text-foreground-600",
              isLoading ? "cursor-wait!" : "",
            )}
            disabled={isLoading}
          >
            <PlusSignIcon className="min-h-[23px] min-w-[23px] text-foreground-600!" />
            <span
              className={`absolute -top-0 -right-0 h-2 w-2 rounded-full bg-primary transition ${currentMode ? "opacity-100" : "opacity-0"}`}
              aria-hidden="true"
            />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          side="top"
          className="w-fit gap-2 rounded-xl border-none bg-surface-100 p-1 text-foreground-50 outline-2! outline-surface-200!"
        >
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
                  posthog.capture("chat:composer_plus_menu_clicked", {
                    item_id: item.id,
                    item_label: item.label,
                    is_mode: item.isMode,
                  });
                  // setLoadingText(item.loadingText ?? "");
                  if (item.isMode) handleSelectionChange(item.id as SearchMode);
                  else if (item.action) item.action();
                }}
                className={cn(
                  "cursor-pointer rounded-lg px-3 py-2",
                  currentMode === item.id
                    ? "bg-[#00bbff50] text-primary focus:bg-[#00bbff50] focus:text-primary"
                    : "focus:bg-surface-200 focus:text-foreground-50",
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
              <Kbd className="text-foreground-400">Press /</Kbd>
            </div>
          }
          placement="right"
          showArrow
        >
          <Button
            size="icon"
            className={cn(
              "group relative flex h-9 w-9 items-center justify-center rounded-full border-none fill-foreground-600 p-0 bg-surface-200 dark:bg-surface-300 hover:bg-surface-300 dark:hover:bg-surface-400 text-foreground-600",
              isLoading ? "cursor-wait!" : "",
              isSlashCommandDropdownOpen &&
                "border-primary/50 bg-primary/20 text-primary hover:bg-primary/40",
            )}
            disabled={isLoading}
            onClick={() => {
              posthog.capture("chat:tools_button_clicked", {
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
