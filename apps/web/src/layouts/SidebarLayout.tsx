import { Button } from "@heroui/button";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import { SidebarHeaderButton } from "@/components";
import SidebarTopButtons from "@/components/layout/sidebar/SidebarTopButtons";
import UserContainer from "@/components/layout/sidebar/UserContainer";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  useSidebar,
} from "@/components/ui/sidebar";
import { SidebarLeft01Icon, SidebarRight01Icon } from "@/icons";

interface SidebarLayoutProps {
  children: ReactNode;
}

// Custom SidebarTrigger with dynamic icons
export const CustomSidebarTrigger = () => {
  const { open, toggleSidebar } = useSidebar();

  return (
    <SidebarHeaderButton
      onClick={toggleSidebar}
      aria-label="Toggle Sidebar"
      tooltip={open ? "Collapse Sidebar" : "Open Sidebar"}
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
  return (
    <Sidebar
      variant="sidebar"
      collapsible="offcanvas"
      className="sidebar border-none!"
    >
      <SidebarHeader className="pb-0">
        <div className="flex items-center justify-between">
          <Link href={"/"}>
            <Button
              className="group ml-2 flex items-center gap-2 px-1"
              size="sm"
              variant="light"
            >
              <Image
                src="/images/logos/text_w_logo_white.webp"
                alt="GAIA Logo"
                width={100}
                height={30}
                className="object-contain"
              />
            </Button>
          </Link>
          <CustomSidebarTrigger />
        </div>
      </SidebarHeader>

      <SidebarContent className="flex-1 px-1">
        <SidebarGroup>
          <SidebarGroupContent className="space-y-1 overflow-hidden">
            <SidebarTopButtons />
            {children}
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="relative z-[4] p-2 px-3 pb-3">
        {/* <ContactSupport /> */}
        <UserContainer />
      </SidebarFooter>
    </Sidebar>
  );
}
