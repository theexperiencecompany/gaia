import {
  BubbleChatAddIcon,
  NotificationIcon,
  PinIcon,
  SearchIcon,
  SidebarLeft01Icon,
  SidebarRight01Icon,
} from "@/icons";
import DemoModelPicker from "./DemoModelPicker";

interface DemoChatHeaderProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  onNotificationsClick: () => void;
}

export default function DemoChatHeader({
  sidebarOpen,
  onToggleSidebar,
  onNotificationsClick,
}: DemoChatHeaderProps) {
  return (
    <div className="flex h-11 shrink-0 items-center justify-between px-3">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onToggleSidebar}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:text-primary"
          aria-label="Toggle sidebar"
        >
          {sidebarOpen ? (
            <SidebarLeft01Icon className="h-5 w-5" />
          ) : (
            <SidebarRight01Icon className="h-5 w-5" />
          )}
        </button>
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
            className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:text-primary"
          >
            <Icon className="h-5 w-5" />
          </button>
        ))}
        <button
          type="button"
          aria-label="Notifications"
          onClick={onNotificationsClick}
          className="relative flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:text-primary"
        >
          <NotificationIcon className="h-5 w-5" />
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-primary" />
        </button>
      </div>
    </div>
  );
}
