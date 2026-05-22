"use client";

import { useDrag } from "@use-gesture/react";
import nextDynamic from "next/dynamic";
import { type ReactNode, useEffect, useRef, useState } from "react";
import HeaderManager from "@/components/layout/headers/HeaderManager";
import StatusBanner from "@/components/layout/StatusBanner";
import Sidebar from "@/components/layout/sidebar/MainSidebar";
import RightSidebar from "@/components/layout/sidebar/RightSidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useOnboardingGuard } from "@/features/auth/hooks/useOnboardingGuard";
import { useUser } from "@/features/auth/hooks/useUser";
import { useIsMobile } from "@/hooks/ui/useMobile";
import { useBackgroundSync } from "@/hooks/useBackgroundSync";
import ProvidersLayout from "@/layouts/ProvidersLayout";
import SidebarLayout, { CustomSidebarTrigger } from "@/layouts/SidebarLayout";
import { useChatStoreSync } from "@/stores/chatStore";
import { useHoloCardModalStore } from "@/stores/holoCardModalStore";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { useUIStoreSidebar } from "@/stores/uiStore";

export const dynamic = "force-dynamic";

const HoloCardModal = nextDynamic(
  () => import("@/features/onboarding/components/HoloCardModal"),
  { ssr: false },
);
const GlobalPricingModal = nextDynamic(
  () =>
    import("@/features/pricing/components/GlobalPricingModal").then((m) => ({
      default: m.GlobalPricingModal,
    })),
  { ssr: false },
);
const CommandMenu = nextDynamic(
  () => import("@/features/search/components/CommandMenu"),
  { ssr: false },
);

const WhatsNewModal = nextDynamic(
  () =>
    import("@/features/whats-new/components/WhatsNewModal").then((m) => ({
      default: m.WhatsNewModal,
    })),
  { ssr: false },
);

const HeaderSidebarTrigger = () => {
  return (
    <div className="">
      <CustomSidebarTrigger />
    </div>
  );
};

export default function MainLayout({ children }: { children: ReactNode }) {
  const user = useUser();
  const { isOpen, isMobileOpen, setOpen, setMobileOpen } = useUIStoreSidebar();
  const {
    content: rightSidebarContent,
    isOpen: rightSidebarOpen,
    variant: rightSidebarVariant,
  } = useRightSidebar();
  const isMobile = useIsMobile();
  const [defaultOpen, setDefaultOpen] = useState(true);
  const dragRef = useRef<HTMLDivElement>(null);
  const [commandMenuOpen, setCommandMenuOpen] = useState(false);
  const { open: isHoloCardModalOpen, closeModal: closeHoloCardModal } =
    useHoloCardModalStore();

  // Check if user needs onboarding
  useOnboardingGuard();
  useBackgroundSync();

  useChatStoreSync();

  // Auto-close sidebar on mobile when pathname changes
  useEffect(() => {
    if (isMobile && isMobileOpen) setMobileOpen(false);
  }, [isMobile, isMobileOpen, setMobileOpen]);

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
    <ProvidersLayout>
      <TooltipProvider>
        <SidebarProvider
          open={currentOpen}
          onOpenChange={handleOpenChange}
          defaultOpen={defaultOpen}
        >
          <div className="relative flex h-screen w-full dark" ref={dragRef}>
            <SidebarLayout>
              <Sidebar />
            </SidebarLayout>

            <SidebarInset className="flex h-screen min-w-0 w-auto flex-col bg-primary-bg">
              <StatusBanner />
              <header
                className="flex shrink-0 items-center justify-between p-2"
                onClick={closeOnTouch}
              >
                <HeaderSidebarTrigger />
                <HeaderManager />
              </header>
              <main className="flex flex-1 flex-col overflow-hidden">
                {/* <Suspense fallback={<SuspenseLoader />}> */}
                {children}
                {/* </Suspense> */}
              </main>
            </SidebarInset>

            <RightSidebar
              isOpen={rightSidebarOpen}
              variant={rightSidebarVariant}
            >
              {rightSidebarContent}
            </RightSidebar>
          </div>

          {/* Global Pricing Modal */}
          <GlobalPricingModal />

          {/* What's New Modal */}
          <WhatsNewModal />

          {/* Global Command Menu */}
          <CommandMenu
            open={commandMenuOpen}
            onOpenChange={setCommandMenuOpen}
          />

          {/* Onboarding Components */}
          <HoloCardModal
            isOpen={isHoloCardModalOpen}
            onClose={closeHoloCardModal}
          />
        </SidebarProvider>
      </TooltipProvider>
    </ProvidersLayout>
  );
}
