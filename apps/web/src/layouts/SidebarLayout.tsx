import { Kbd } from "@heroui/kbd";
import { SidebarLeft01Icon, SidebarRight01Icon } from "@icons";
import type { ReactNode } from "react";
import { SidebarHeaderButton } from "@/components/layout/headers/SidebarHeaderButton";
import ContactSupport from "@/components/layout/sidebar/ContactSupport";
import SidebarTopButtons from "@/components/layout/sidebar/SidebarTopButtons";
import UserContainer from "@/components/layout/sidebar/UserContainer";
import { LogoWithContextMenu } from "@/components/shared/LogoWithContextMenu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  useSidebar,
} from "@/components/ui/sidebar";
import { WhatsNewCard } from "@/features/whats-new/components/WhatsNewCard";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { useElectron } from "@/hooks/useElectron";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { cn } from "@/lib/utils";

interface SidebarLayoutProps {
  children: ReactNode;
}

interface CustomSidebarTriggerProps {
  className?: string;
}

// Custom SidebarTrigger with dynamic icons
export const CustomSidebarTrigger = ({
  className,
}: CustomSidebarTriggerProps) => {
  const { open, toggleSidebar } = useSidebar();
  const { isMac } = usePlatform();

  const handleToggle = () => {
    trackEvent(
      open
        ? ANALYTICS_EVENTS.UI_SIDEBAR_COLLAPSED
        : ANALYTICS_EVENTS.UI_SIDEBAR_EXPANDED,
    );
    toggleSidebar();
  };

  return (
    <SidebarHeaderButton
      onClick={handleToggle}
      aria-label="Toggle Sidebar"
      className={className}
      tooltip={
        <span className="flex items-center gap-2 text-xs">
          {open ? "Collapse Sidebar" : "Open Sidebar"}
          <div>
            <Kbd className="text-xs">{isMac ? "⌘" : "Ctrl"}</Kbd>
            <Kbd className="text-xs">B</Kbd>
          </div>
        </span>
      }
    >
      {open ? (
        <SidebarLeft01Icon className="max-h-5 min-h-5 max-w-5 min-w-5 text-zinc-500 transition group-hover/btn:text-primary" />
      ) : (
        <SidebarRight01Icon className="max-h-5 min-h-5 max-w-5 min-w-5 text-zinc-500 transition group-hover/btn:text-primary" />
      )}
    </SidebarHeaderButton>
  );
};

export default function SidebarLayout({ children }: SidebarLayoutProps) {
  const { isElectron } = useElectron();
  const { isMac } = usePlatform();

  return (
    <Sidebar variant="sidebar" collapsible="offcanvas">
      {/* In the desktop app the window chrome owns the top-left corner:
          no logo, and on macOS extra top padding clears the traffic
          lights (hiddenInset title bar, lights at y=16). The empty strip
          is part of the title bar too — the sidebar slides under the
          content header, so without this the top-left corner is a drag
          dead zone whenever the sidebar is expanded. */}
      <SidebarHeader
        className={cn("pb-0", isElectron && isMac && "pt-10 electron-drag")}
      >
        {!isElectron && (
          <div className="flex items-center justify-between pb-0">
            <LogoWithContextMenu className="group ml-2 flex items-center" />
          </div>
        )}
      </SidebarHeader>

      <SidebarContent className="flex-1">
        <SidebarGroup>
          <SidebarGroupContent className="overflow-hidden">
            <div className="space-y-1 overflow-hidden">
              <SidebarTopButtons />
              {children}
            </div>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="relative z-4">
        <div className="flex flex-col gap-2 p-2 px-3 pb-3">
          <WhatsNewCard />
          <UserContainer />
          <ContactSupport />
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
