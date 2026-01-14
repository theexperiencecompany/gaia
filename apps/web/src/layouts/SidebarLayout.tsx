"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { SidebarHeaderButton } from "@/components";
import ContactSupport from "@/components/layout/sidebar/ContactSupport";
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
import { usePlatform } from "@/hooks/ui/usePlatform";
import { SidebarLeft01Icon, SidebarRight01Icon } from "@/icons";
import { useTheme } from "@/components/providers/ThemeProvider";

interface SidebarLayoutProps {
  children: ReactNode;
}

// Custom SidebarTrigger with dynamic icons
export const CustomSidebarTrigger = () => {
  const { open, toggleSidebar } = useSidebar();
  const { isMac } = usePlatform();

  return (
    <SidebarHeaderButton
      onClick={toggleSidebar}
      aria-label="Toggle Sidebar"
      tooltip={
        <span className="flex items-center gap-2 text-xs">
          {open ? "Collapse Sidebar" : "Open Sidebar"}
          <div>
            <Kbd className="text-xs rounded-md">{isMac ? "⌘" : "Ctrl"}</Kbd>
            <Kbd className="text-xs rounded-md">B</Kbd>
          </div>
        </span>
      }
    >
      {open ? (
        <SidebarLeft01Icon className="max-h-5 min-h-5 max-w-5 min-w-5 text-foreground-500 transition group-hover/btn:text-primary" />
      ) : (
        <SidebarRight01Icon className="max-h-5 min-h-5 max-w-5 min-w-5 text-foreground-500 transition group-hover/btn:text-primary" />
      )}
    </SidebarHeaderButton>
  );
};

export default function SidebarLayout({ children }: SidebarLayoutProps) {
  const { resolvedTheme } = useTheme();
  const logoSrc = resolvedTheme === "dark" 
    ? "/images/logos/text_w_logo_white.webp"
    : "/images/logos/text_w_logo_black.webp";

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
                src={logoSrc}
                alt="GAIA Logo"
                width={100}
                height={30}
                className="object-contain"
              />
            </Button>
          </Link>
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

      <SidebarFooter className="relative z-4 p-2 px-3 pb-3">
        <UserContainer />
        <ContactSupport />
      </SidebarFooter>
    </Sidebar>
  );
}
