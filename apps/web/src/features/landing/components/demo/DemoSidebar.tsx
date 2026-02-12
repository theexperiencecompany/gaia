"use client";

import { Button } from "@heroui/button";
import { motion } from "framer-motion";
import { useState } from "react";

import { LogoWithContextMenu } from "@/components/shared/LogoWithContextMenu";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { BubbleChatAddIcon, ChevronsDownUp, ChevronsUpDown } from "@/icons";
import DemoChatTab from "./DemoChatTab";
import DemoSettingsDropdown from "./DemoSettingsDropdown";
import { CHAT_GROUPS, ease, NAV_BUTTONS } from "./demoConstants";

interface DemoSidebarProps {
  open: boolean;
}

export default function DemoSidebar({ open }: DemoSidebarProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <motion.div
      animate={{ width: open ? 240 : 0, opacity: open ? 1 : 0 }}
      transition={{ duration: 0.22, ease }}
      className="relative flex shrink-0 flex-col overflow-hidden backdrop-blur-2xl"
      style={{ backgroundColor: "#1a1a1add" }}
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
              {NAV_BUTTONS.map(({ Icon, label, active }) => (
                <Button
                  key={label}
                  size="sm"
                  variant={active ? "flat" : "light"}
                  color="default"
                  className={`w-full justify-start text-sm focus-visible:outline-none ${
                    active
                      ? "text-zinc-300"
                      : "text-zinc-400 hover:text-zinc-300"
                  }`}
                >
                  <div className="flex w-full items-center gap-2">
                    <div className="flex w-4.25 min-w-4.25 items-center justify-center">
                      <Icon width={18} height={18} />
                    </div>
                    <span className="w-[calc(100%-45px)] max-w-[200px] truncate text-left">
                      {label}
                    </span>
                  </div>
                </Button>
              ))}
            </div>

            {/* New Chat — mirrors MainSidebar exactly */}
            <div className="flex w-full justify-center">
              <Button
                color="primary"
                size="sm"
                fullWidth
                variant="flat"
                className="mb-4 mt-1 flex justify-start text-sm font-medium text-primary"
                startContent={<BubbleChatAddIcon width={18} height={18} />}
              >
                New Chat
              </Button>
            </div>
          </div>

          {/* Chat list — exact accordionItemStyles from constants.ts */}
          <div className="flex-1 overflow-y-auto">
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
          </div>
        </div>

        {/* Footer — mirrors SidebarFooter p-2 px-3 pb-3 */}
        <div className="p-2 px-3 pb-3">
          <DemoSettingsDropdown onOpenChange={setSettingsOpen}>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 rounded-xl bg-transparent px-2 py-3 transition-colors hover:bg-zinc-800 cursor-pointer"
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
                  <span className="text-xs font-medium text-zinc-200">
                    Aryan Randeriya
                  </span>
                  <span className="text-[10px] text-zinc-500">GAIA Pro</span>
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
    </motion.div>
  );
}
