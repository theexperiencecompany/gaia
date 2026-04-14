"use client";

import { Button } from "@heroui/button";
import {
  BubbleChatAddIcon,
  Calendar01Icon,
  Calendar03Icon,
  CalendarUpload02Icon,
  CheckListIcon,
  ConnectIcon,
  Flag02Icon,
  Folder02Icon,
  InboxCheckIcon,
  InboxIcon,
  InternetIcon,
  Tag01Icon,
  ViewIcon,
} from "@icons";
import * as m from "motion/react-m";
import type { MouseEvent } from "react";
import { memo, useCallback, useMemo, useState } from "react";
import {
  ChevronsDownUp,
  ChevronsUpDown,
  ZapIcon,
} from "@/components/shared/icons";
import { LogoWithContextMenu } from "@/components/shared/LogoWithContextMenu";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import DemoChatTab from "./DemoChatTab";
import DemoSettingsDropdown from "./DemoSettingsDropdown";
import { CHAT_GROUPS, ease, NAV_BUTTONS } from "./demoConstants";
import type { DemoPage } from "./types";

const SIDEBAR_WIDTH = 240;

const sidebarVariants = {
  open: { width: SIDEBAR_WIDTH, opacity: 1 },
  closed: { width: 0, opacity: 0 },
};

const sidebarTransition = { duration: 0.22, ease };

const CALENDARS = [
  { name: "Primary", color: "#00bbff" },
  { name: "Work", color: "#7c3aed" },
  { name: "Personal", color: "#10b981" },
];

const WORKFLOWS = [
  { title: "Daily Email Digest", categories: ["gmail", "slack"] },
  { title: "PR Review Notifier", categories: ["github", "slack"] },
  { title: "Weekly Standup", categories: ["linear", "github"] },
  { title: "Meeting Notes", categories: ["googlecalendar", "notion"] },
];

const INTEGRATIONS = [
  { id: "gmail", name: "Gmail", status: "connected" as const },
  {
    id: "googlecalendar",
    name: "Google Calendar",
    status: "connected" as const,
  },
  { id: "slack", name: "Slack", status: "connected" as const },
  { id: "github", name: "GitHub", status: "connected" as const },
  { id: "notion", name: "Notion", status: "connected" as const },
  {
    id: "linear",
    name: "Linear",
    status: "connected" as const,
    isPublic: true,
  },
  {
    id: "todoist",
    name: "Todoist",
    status: "created" as const,
    isPublic: true,
  },
  { id: "asana", name: "Asana", status: "created" as const, isPublic: true },
];

const TODO_MAIN_MENU = [
  { label: "Inbox", Icon: InboxIcon, count: 4, active: true },
  { label: "Today", Icon: Calendar01Icon, count: 3, active: false },
  { label: "Upcoming", Icon: CalendarUpload02Icon, count: 7, active: false },
  { label: "Completed", Icon: InboxCheckIcon, count: 2, active: false },
];

const TODO_PRIORITIES = [
  { label: "High Priority", color: "#ef4444" },
  { label: "Medium Priority", color: "#eab308" },
  { label: "Low Priority", color: "#3b82f6" },
];

const TODO_LABELS = [
  { name: "content", count: 1 },
  { name: "marketing", count: 1 },
  { name: "infra", count: 1 },
  { name: "learning", count: 1 },
];

const TODO_PROJECTS = [
  { name: "GAIA", color: "#00bbff", count: 5 },
  { name: "Personal", color: "#10b981", count: 3 },
  { name: "Marketing", color: "#f59e0b", count: 2 },
];

const ChatsSidebarContent = memo(function ChatsSidebarContent() {
  return (
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
  );
});

const CalendarSidebarContent = memo(function CalendarSidebarContent() {
  return (
    <div className="px-2">
      <p className="px-2 pb-1 text-xs font-normal text-zinc-600">
        Your Calendars
      </p>
      <div className="flex flex-col gap-1">
        {CALENDARS.map((cal) => (
          <div
            key={cal.name}
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800 cursor-pointer"
          >
            <div
              className="h-3 w-3 rounded-full shrink-0"
              style={{ backgroundColor: cal.color }}
            />
            <span className="flex-1 truncate">{cal.name}</span>
            <ViewIcon width={16} height={16} className="text-zinc-500" />
          </div>
        ))}
      </div>
    </div>
  );
});

const WorkflowsSidebarContent = memo(function WorkflowsSidebarContent() {
  return (
    <div className="px-2">
      <p className="px-2 pb-1 text-xs font-normal text-zinc-600">
        Your Workflows
      </p>
      <div className="flex flex-col gap-1">
        {WORKFLOWS.map((wf) => (
          <div
            key={wf.title}
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300 cursor-pointer"
          >
            <div className="flex -space-x-1">
              {wf.categories.slice(0, 2).map((cat, i) => (
                <div key={cat} className="relative" style={{ zIndex: i }}>
                  {getToolCategoryIcon(cat, { width: 16, height: 16 })}
                </div>
              ))}
            </div>
            <span className="flex-1 truncate">{wf.title}</span>
          </div>
        ))}
      </div>
    </div>
  );
});

interface IntegrationsSidebarContentProps {
  selectedIntegrationId?: string | null;
  onIntegrationSelect?: (id: string) => void;
}

const IntegrationsSidebarContent = memo(function IntegrationsSidebarContent({
  selectedIntegrationId,
  onIntegrationSelect,
}: IntegrationsSidebarContentProps) {
  return (
    <div className="px-2">
      <p className="px-2 pb-1 text-xs font-normal text-zinc-600">
        Integrations
      </p>
      <div className="flex flex-col gap-0.5">
        {INTEGRATIONS.map((integration) => (
          <div
            key={integration.id}
            onClick={() => onIntegrationSelect?.(integration.id)}
            className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm cursor-pointer transition-colors ${
              selectedIntegrationId === integration.id
                ? "bg-zinc-800 text-zinc-300"
                : "text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
            }`}
          >
            {getToolCategoryIcon(integration.id, {
              width: 18,
              height: 18,
              showBackground: false,
            })}
            <span className="flex-1 truncate">{integration.name}</span>
            <div className="flex items-center gap-1.5">
              {integration.isPublic && (
                <InternetIcon width={14} height={14} className="text-primary" />
              )}
              {integration.status === "connected" && (
                <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
              )}
              {integration.status === "created" && (
                <span className="h-1.5 w-1.5 rounded-full bg-yellow-500" />
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

const TodosSidebarContent = memo(function TodosSidebarContent() {
  return (
    <div className="flex flex-col space-y-3 px-2">
      <div className="flex flex-col gap-0.5">
        {TODO_MAIN_MENU.map((item) => (
          <div
            key={item.label}
            className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm cursor-pointer ${
              item.active
                ? "bg-zinc-800 text-zinc-300"
                : "text-zinc-500 hover:bg-zinc-800/50 hover:text-zinc-300"
            }`}
          >
            <item.Icon width={18} height={18} />
            <span className="flex-1 truncate">{item.label}</span>
            <span className="ml-auto text-xs">{item.count}</span>
          </div>
        ))}
      </div>

      <div>
        <p className="mb-1 px-2 text-xs font-normal text-zinc-600">
          Priorities
        </p>
        <div className="flex flex-col gap-0.5">
          {TODO_PRIORITIES.map((item) => (
            <div
              key={item.label}
              className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800/50 hover:text-zinc-300 cursor-pointer"
            >
              <Flag02Icon
                width={18}
                height={18}
                style={{ color: item.color }}
              />
              <span className="flex-1 truncate">{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-1 px-2 text-xs font-normal text-zinc-600">Labels</p>
        <div className="flex flex-col gap-0.5">
          {TODO_LABELS.map((label) => (
            <div
              key={label.name}
              className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800/50 hover:text-zinc-300 cursor-pointer"
            >
              <Tag01Icon width={18} height={18} />
              <span className="flex-1 truncate">
                {label.name.charAt(0).toUpperCase() + label.name.slice(1)}
              </span>
              <span className="ml-auto text-xs">{label.count}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-1 px-2 text-xs font-normal text-zinc-600">Projects</p>
        <div className="flex flex-col gap-0.5">
          {TODO_PROJECTS.map((project) => (
            <div
              key={project.name}
              className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800/50 hover:text-zinc-300 cursor-pointer"
            >
              <Folder02Icon
                width={18}
                height={18}
                style={{ color: project.color }}
              />
              <span className="flex-1 truncate">{project.name}</span>
              <span className="ml-auto text-xs">{project.count}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});

const getSidebarContent = (
  activePage: DemoPage,
  props: IntegrationsSidebarContentProps,
) => {
  switch (activePage) {
    case "chats":
      return <ChatsSidebarContent />;
    case "calendar":
      return <CalendarSidebarContent />;
    case "workflows":
      return <WorkflowsSidebarContent />;
    case "integrations":
      return <IntegrationsSidebarContent {...props} />;
    case "todos":
      return <TodosSidebarContent />;
    default:
      return null;
  }
};

interface DemoSidebarProps {
  open: boolean;
  activePage: DemoPage;
  onPageChange: (page: DemoPage) => void;
  selectedIntegrationId?: string | null;
  onIntegrationSelect?: (id: string) => void;
}

const DemoSidebar = memo(function DemoSidebar({
  open,
  activePage,
  onPageChange,
  selectedIntegrationId,
  onIntegrationSelect,
}: DemoSidebarProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  const handleNavButtonClick = useCallback(
    (event: MouseEvent<HTMLButtonElement>, page?: DemoPage) => {
      event.preventDefault();
      event.stopPropagation();
      if (page) onPageChange(page);
    },
    [onPageChange],
  );

  const handleIntegrationSelect = useCallback(
    (id: string) => {
      onIntegrationSelect?.(id);
    },
    [onIntegrationSelect],
  );

  const handleSettingsOpenChange = useCallback((nextOpen: boolean) => {
    setSettingsOpen(nextOpen);
  }, []);

  const primaryAction = useMemo(() => {
    switch (activePage) {
      case "calendar":
        return {
          label: "New Event",
          icon: <Calendar03Icon width={18} height={18} />,
        };
      case "workflows":
        return {
          label: "New Workflow",
          icon: <ZapIcon width={18} height={18} />,
        };
      case "integrations":
        return {
          label: "Create Custom",
          icon: <ConnectIcon width={18} height={18} />,
        };
      case "todos":
        return {
          label: "New Todo",
          icon: <CheckListIcon width={18} height={18} />,
        };
      case "chats":
      default:
        return {
          label: "New Chat",
          icon: <BubbleChatAddIcon width={18} height={18} />,
        };
    }
  }, [activePage]);

  return (
    <m.div
      initial={false}
      animate={open ? "open" : "closed"}
      variants={sidebarVariants}
      transition={sidebarTransition}
      className="relative flex shrink-0 flex-col overflow-hidden backdrop-blur-2xl"
      style={{ backgroundColor: "#1a1a1abb" }}
    >
      <div
        className="flex h-full w-60 flex-col"
        style={{ width: SIDEBAR_WIDTH }}
      >
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
                  <button
                    key={label}
                    type="button"
                    onClick={(event) => handleNavButtonClick(event, page)}
                    className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors ${isActive ? "bg-zinc-800 text-zinc-300" : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-300"} ${page ? "cursor-pointer" : "cursor-default opacity-60"}`}
                  >
                    <div className="flex w-4.25 min-w-4.25 items-center justify-center">
                      <Icon width={18} height={18} />
                    </div>
                    <span className="w-[calc(100%-45px)] max-w-50 truncate text-left">
                      {label}
                    </span>
                  </button>
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
                startContent={primaryAction.icon}
              >
                {primaryAction.label}
              </Button>
            </div>
          </div>

          {/* Page-specific sidebar content */}
          <div className="flex-1 overflow-y-auto">
            {getSidebarContent(activePage, {
              selectedIntegrationId,
              onIntegrationSelect: handleIntegrationSelect,
            })}
          </div>
        </div>

        {/* Footer — mirrors SidebarFooter p-2 px-3 pb-3 */}
        <div className="p-2 px-3 pb-3">
          <DemoSettingsDropdown onOpenChange={handleSettingsOpenChange}>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-3 rounded-2xl bg-transparent px-2 py-1 transition-colors hover:bg-zinc-800 cursor-pointer"
            >
              <div className="flex items-center gap-2.5">
                <Avatar className="size-7 shrink-0 rounded-full bg-black">
                  <AvatarImage
                    src="https://avatars.githubusercontent.com/u/64796509?v=3&s=56"
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
                  <span className="text-xs text-zinc-400">GAIA Pro</span>
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
});

export default DemoSidebar;
