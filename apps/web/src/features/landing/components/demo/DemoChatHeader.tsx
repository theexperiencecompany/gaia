import {
  BubbleChatAddIcon,
  Calendar03Icon,
  CheckListIcon,
  ConnectIcon,
  DashboardSquare02Icon,
  NotificationIcon,
  PinIcon,
  SearchIcon,
  SidebarLeft01Icon,
  SidebarRight01Icon,
  ZapIcon,
} from "@icons";
import type { ComponentType, SVGAttributes } from "react";
import DemoModelPicker from "./DemoModelPicker";
import type { DemoPage } from "./types";

const PAGE_META: Record<
  Exclude<DemoPage, "chats">,
  { Icon: ComponentType<SVGAttributes<SVGElement>>; title: string }
> = {
  dashboard: { Icon: DashboardSquare02Icon, title: "Dashboard" },
  calendar: { Icon: Calendar03Icon, title: "Calendar" },
  workflows: { Icon: ZapIcon, title: "Workflows" },
  integrations: { Icon: ConnectIcon, title: "Integrations" },
  todos: { Icon: CheckListIcon, title: "Todos" },
};

interface DemoChatHeaderProps {
  sidebarOpen: boolean;
  activePage: DemoPage;
  onToggleSidebar: () => void;
  onNotificationsClick: () => void;
}

export default function DemoChatHeader({
  sidebarOpen,
  activePage,
  onToggleSidebar,
  onNotificationsClick,
}: DemoChatHeaderProps) {
  const sidebarToggle = (
    <button
      type="button"
      onClick={onToggleSidebar}
      className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-zinc-400 transition-colors hover:text-primary"
      aria-label="Toggle sidebar"
    >
      {sidebarOpen ? (
        <SidebarLeft01Icon className="h-5 w-5" />
      ) : (
        <SidebarRight01Icon className="h-5 w-5" />
      )}
    </button>
  );

  const notificationsButton = (
    <button
      type="button"
      aria-label="Notifications"
      onClick={onNotificationsClick}
      className="relative flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:text-primary"
    >
      <NotificationIcon className="h-5 w-5" />
      <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-primary" />
    </button>
  );

  if (activePage !== "chats") {
    const { Icon, title } = PAGE_META[activePage];
    return (
      <div className="flex h-11 shrink-0 items-center justify-between px-3">
        <div className="flex items-center gap-1">
          {sidebarToggle}
          <div className="flex items-center gap-2 pl-0 text-zinc-500">
            <Icon className="h-5 w-5" />
            <span>{title}</span>
          </div>
        </div>
        <div className="flex items-center">{notificationsButton}</div>
      </div>
    );
  }

  return (
    <div className="flex h-11 shrink-0 items-center justify-between px-3">
      <div className="flex items-center gap-1">
        {sidebarToggle}
        <DemoModelPicker />
      </div>
      <div className="flex items-center">
        {[
          { Icon: SearchIcon, label: "Search" },
          { Icon: PinIcon, label: "Pins" },
          { Icon: BubbleChatAddIcon, label: "New Chat" },
        ].map(({ Icon, label }) => (
          <button
            key={label}
            type="button"
            aria-label={label}
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-zinc-400 transition-colors hover:text-primary"
          >
            <Icon className="h-5 w-5" />
          </button>
        ))}
        {notificationsButton}
      </div>
    </div>
  );
}
