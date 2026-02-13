"use client";

import { Button } from "@heroui/button";
import { m } from "motion/react";
import { useState } from "react";

import { LogoWithContextMenu } from "@/components/shared/LogoWithContextMenu";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  BubbleChatAddIcon,
  Calendar03Icon,
  ChevronsDownUp,
  ChevronsUpDown,
  ConnectIcon,
  ViewIcon,
  ZapIcon,
} from "@/icons";
import DemoChatTab from "./DemoChatTab";
import DemoSettingsDropdown from "./DemoSettingsDropdown";
import { CHAT_GROUPS, ease, NAV_BUTTONS } from "./demoConstants";
import type { DemoPage } from "./types";

interface DemoSidebarProps {
  open: boolean;
  activePage: DemoPage;
  onPageChange: (page: DemoPage) => void;
}

export default function DemoSidebar({
  open,
  activePage,
  onPageChange,
}: DemoSidebarProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <m.div
      animate={{ width: open ? 240 : 0, opacity: open ? 1 : 0 }}
      transition={{ duration: 0.22, ease }}
      className="relative flex shrink-0 flex-col overflow-hidden backdrop-blur-2xl"
      style={{ backgroundColor: "#1a1a1abb" }}
    >
      <div className="flex h-full w-60 flex-col">
        {/* Logo */}
        <div className="flex items-center px-2 py-2">
          <LogoWithContextMenu
            className="group flex items-center gap-2 px-1"
            width={80}
            height={24}
          />
        </div>

        {/* SidebarContent — px-1 matches real SidebarContent className="flex-1 px-1" */}
        <div className="flex flex-1 flex-col overflow-hidden px-2">
          {/* Nav — mirrors SidebarTopButtons + SidebarGroupContent space-y-1 */}
          <div className="space-y-1 overflow-hidden">
            <div className="flex w-full flex-col gap-0.5">
              {NAV_BUTTONS.map(({ Icon, label, page }) => {
                const isActive = page === activePage;
                return (
                  <Button
                    key={label}
                    size="sm"
                    variant={isActive ? "flat" : "light"}
                    color="default"
                    className={`w-full justify-start text-sm focus-visible:outline-none ${
                      isActive
                        ? "text-zinc-300"
                        : "text-zinc-400 hover:text-zinc-300"
                    }`}
                    onPress={() => page && onPageChange(page)}
                  >
                    <div className="flex w-full items-center gap-2">
                      <div className="flex w-4.25 min-w-4.25 items-center justify-center">
                        <Icon width={18} height={18} />
                      </div>
                      <span className="w-[calc(100%-45px)] max-w-50 truncate text-left">
                        {label}
                      </span>
                    </div>
                  </Button>
                );
              })}
            </div>

            {/* Primary action button — changes per page */}
            <div className="flex w-full justify-center">
              <Button
                color="primary"
                size="sm"
                fullWidth
                variant="flat"
                className="mb-4 mt-1 flex justify-start text-sm font-medium text-primary"
                startContent={
                  activePage === "chats" ? (
                    <BubbleChatAddIcon width={18} height={18} />
                  ) : activePage === "calendar" ? (
                    <Calendar03Icon width={18} height={18} />
                  ) : activePage === "workflows" ? (
                    <ZapIcon width={18} height={18} />
                  ) : activePage === "integrations" ? (
                    <ConnectIcon width={18} height={18} />
                  ) : null
                }
              >
                {activePage === "chats"
                  ? "New Chat"
                  : activePage === "calendar"
                    ? "New Event"
                    : activePage === "workflows"
                      ? "New Workflow"
                      : activePage === "integrations"
                        ? "Create Custom"
                        : "New Chat"}
              </Button>
            </div>
          </div>

          {/* Page-specific sidebar content */}
          <div className="flex-1 overflow-y-auto">
            {activePage === "chats" && (
              <Accordion
                type="multiple"
                defaultValue={["Today", "Yesterday", "Last 30 days"]}
                className="w-full p-0"
              >
                {Object.entries(CHAT_GROUPS).map(([group, tabs]) => (
                  <AccordionItem
                    key={group}
                    value={group}
                    className="my-1 flex min-h-fit w-full flex-col items-start justify-start overflow-hidden border-none py-1"
                  >
                    <AccordionTrigger className="w-full px-2 pb-1 pt-0 text-xs font-normal text-zinc-600 hover:text-zinc-600 hover:no-underline">
                      {group}
                    </AccordionTrigger>
                    <AccordionContent className="w-full p-0!">
                      <div className="flex w-full flex-col gap-1">
                        {tabs.map((tab) => (
                          <DemoChatTab
                            key={tab.id}
                            label={tab.label}
                            active={tab.active}
                          />
                        ))}
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            )}

            {activePage === "calendar" && (
              <div className="px-2">
                <p className="px-2 pb-1 text-xs font-normal text-zinc-600">
                  Your Calendars
                </p>
                <div className="flex flex-col gap-1">
                  {[
                    { name: "Primary", color: "#00bbff" },
                    { name: "Work", color: "#7c3aed" },
                    { name: "Personal", color: "#10b981" },
                  ].map((cal) => (
                    <div
                      key={cal.name}
                      className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800 cursor-pointer"
                    >
                      <div
                        className="h-3 w-3 rounded-full shrink-0"
                        style={{ backgroundColor: cal.color }}
                      />
                      <span className="flex-1 truncate">{cal.name}</span>
                      <ViewIcon
                        width={16}
                        height={16}
                        className="text-zinc-500"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {activePage === "workflows" && (
              <div className="px-2">
                <p className="px-2 pb-1 text-xs font-normal text-zinc-600">
                  Your Workflows
                </p>
                <div className="flex flex-col gap-1">
                  {[
                    {
                      title: "Daily Email Digest",
                      categories: ["gmail", "slack"],
                    },
                    {
                      title: "PR Review Notifier",
                      categories: ["github", "slack"],
                    },
                    {
                      title: "Weekly Standup",
                      categories: ["linear", "github"],
                    },
                    {
                      title: "Meeting Notes",
                      categories: ["googlecalendar", "notion"],
                    },
                  ].map((wf) => (
                    <div
                      key={wf.title}
                      className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300 cursor-pointer"
                    >
                      <div className="flex -space-x-1">
                        {wf.categories.slice(0, 2).map((cat, i) => (
                          <div
                            key={cat}
                            className="relative"
                            style={{ zIndex: i }}
                          >
                            {getToolCategoryIcon(cat, {
                              width: 16,
                              height: 16,
                            })}
                          </div>
                        ))}
                      </div>
                      <span className="flex-1 truncate">{wf.title}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {activePage === "integrations" && (
              <div className="px-2">
                <p className="px-2 pb-1 text-xs font-normal text-zinc-600">
                  Connected
                </p>
                <div className="flex flex-col gap-1">
                  {[
                    "gmail",
                    "googlecalendar",
                    "slack",
                    "github",
                    "notion",
                    "linear",
                  ].map((id) => (
                    <div
                      key={id}
                      className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300 cursor-pointer"
                    >
                      {getToolCategoryIcon(id, {
                        width: 18,
                        height: 18,
                        showBackground: false,
                      })}
                      <span className="flex-1 truncate capitalize">
                        {id === "googlecalendar"
                          ? "Google Calendar"
                          : id === "gmail"
                            ? "Gmail"
                            : id.charAt(0).toUpperCase() + id.slice(1)}
                      </span>
                      <div className="h-2 w-2 rounded-full bg-green-500" />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer — mirrors SidebarFooter p-2 px-3 pb-3 */}
        <div className="p-2 px-3 pb-3">
          <DemoSettingsDropdown onOpenChange={setSettingsOpen}>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 rounded-2xl bg-transparent px-2 py-1 transition-colors hover:bg-zinc-800 cursor-pointer"
            >
              <div className="flex items-center gap-2.5">
                <Avatar className="size-7 shrink-0 rounded-full bg-black">
                  <AvatarImage
                    src="https://github.com/aryanranderiya.png"
                    alt="Aryan"
                  />
                  <AvatarFallback className="bg-zinc-700 text-xs text-zinc-300">
                    AR
                  </AvatarFallback>
                </Avatar>
                <div className="flex flex-col items-start space-y-1">
                  <span className="text-sm font-medium text-zinc-200">
                    Aryan Randeriya
                  </span>
                  <span className="text-xs text-zinc-500">GAIA Pro</span>
                </div>
              </div>
              {settingsOpen ? (
                <ChevronsDownUp
                  className="shrink-0 text-zinc-500"
                  width={16}
                  height={16}
                />
              ) : (
                <ChevronsUpDown
                  className="shrink-0 text-zinc-500"
                  width={16}
                  height={16}
                />
              )}
            </button>
          </DemoSettingsDropdown>
        </div>
      </div>
    </m.div>
  );
}
