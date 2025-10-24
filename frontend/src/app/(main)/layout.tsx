"use client";

import { useDrag } from "@use-gesture/react";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useRef, useState } from "react";

import HeaderManager from "@/components/layout/headers/HeaderManager";
import Sidebar from "@/components/layout/sidebar/MainSidebar";
import RightSidebar from "@/components/layout/sidebar/RightSidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/shadcn/sidebar";
import { TooltipProvider } from "@/components/ui/shadcn/tooltip";
import { useOnboardingGuard } from "@/features/auth/hooks/useOnboardingGuard";
import CommandMenu from "@/features/search/components/CommandMenu";
import { useIsMobile } from "@/hooks/ui/useMobile";
import SidebarLayout, { CustomSidebarTrigger } from "@/layouts/SidebarLayout";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { useUIStoreSidebar } from "@/stores/uiStore";

const HeaderSidebarTrigger = () => {
  return (
    <div className="pt-1">
      <CustomSidebarTrigger />
    </div>
  );
};

export default function MainLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { isOpen, isMobileOpen, setOpen, setMobileOpen } = useUIStoreSidebar();
  const { content: rightSidebarContent, isOpen: rightSidebarOpen } =
    useRightSidebar();
  const isMobile = useIsMobile();
  const [defaultOpen, setDefaultOpen] = useState(true);
  const dragRef = useRef<HTMLDivElement>(null);
  const [commandMenuOpen, setCommandMenuOpen] = useState(false);

  // Check if user needs onboarding
  useOnboardingGuard();

  // Auto-close sidebar on mobile when pathname changes
  useEffect(() => {
    if (isMobile && isMobileOpen) setMobileOpen(false);
  }, [pathname, isMobile, isMobileOpen, setMobileOpen]);

  // Set default open state based on screen size
  useEffect(() => {
    if (isMobile) setDefaultOpen(false);
    else setDefaultOpen(true);
  }, [isMobile]);

  function closeOnTouch(): void {
    if (isMobile && (isMobileOpen || isOpen)) setMobileOpen(false);
  }

  function handleOpenChange(open: boolean): void {
    if (isMobile) {
      setMobileOpen(open);
    } else {
      setOpen(open);
    }
  }

  // Get the current open state based on mobile/desktop
  const currentOpen = isMobile ? isMobileOpen : isOpen;

  // @warning: Removing the `target` option from useDrag will cause the HeroUI Buttons to not work properly.
  // For more details, see: https://github.com/hey-gaia/gaia/issues/44
  useDrag(
    ({ movement: [mx, my], last, tap }) => {
      // If this is just a tap, do nothing—allow click events to proceed.
      if (tap || !isMobile) return;

      if (last && Math.abs(mx) > Math.abs(my)) {
        if (mx > 0)
          // Swipe right to open
          setMobileOpen(true);
        else if (mx < 0)
          // Swipe left to close
          setMobileOpen(false);
      }
    },
    {
      filterTaps: true, // Taps are ignored for swipe detection.
      threshold: 10, // Minimal movement before detecting a swipe.
      axis: "x", // Only track horizontal swipes.
      target: dragRef,
      // preventDefault: false, // Prevent default touch actions to avoid conflicts.
      // eventOptions: { passive: false }, // Ensure we can prevent default behavior.
    },
  );

  return (
    <TooltipProvider>
      <SidebarProvider
        open={currentOpen}
        onOpenChange={handleOpenChange}
        defaultOpen={defaultOpen}
      >
        <div
          className="flex min-h-screen w-full dark"
          style={{ touchAction: "pan-y" }}
          ref={dragRef}
        >
          <SidebarLayout>
            <Sidebar />
          </SidebarLayout>

          <SidebarInset className="flex h-screen flex-col bg-[#1a1a1a]">
            <header
              className="flex flex-shrink-0 items-center justify-between px-6 py-3 pl-3"
              onClick={closeOnTouch}
            >
              {!currentOpen && <HeaderSidebarTrigger />}
              <HeaderManager />
            </header>
            <main className="flex flex-1 flex-col overflow-hidden">
              {children}
            </main>
          </SidebarInset>

          <RightSidebar isOpen={rightSidebarOpen}>
            {rightSidebarContent}
          </RightSidebar>
        </div>

        {/* Global Command Menu */}
        <CommandMenu open={commandMenuOpen} onOpenChange={setCommandMenuOpen} />
      </SidebarProvider>
    </TooltipProvider>
  );
}
