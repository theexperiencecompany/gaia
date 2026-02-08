"use client";

import { useDrag } from "@use-gesture/react";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState } from "react";

export const dynamic = "force-dynamic";

import HeaderManager from "@/components/layout/headers/HeaderManager";
import Sidebar from "@/components/layout/sidebar/MainSidebar";
import RightSidebar from "@/components/layout/sidebar/RightSidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useOnboardingGuard } from "@/features/auth/hooks/useOnboardingGuard";
import { useUser } from "@/features/auth/hooks/useUser";
import ContextGatheringLoader from "@/features/onboarding/components/ContextGatheringLoader";
import HoloCardModal from "@/features/onboarding/components/HoloCardModal";
import { isOnboardingPhaseUpdateMessage } from "@/features/onboarding/types/websocket";
import CommandMenu from "@/features/search/components/CommandMenu";
import { useIsMobile } from "@/hooks/ui/useMobile";
import { useBackgroundSync } from "@/hooks/useBackgroundSync";
import { useOAuthSuccessToast } from "@/hooks/useOAuthSuccessToast";
import SidebarLayout, { CustomSidebarTrigger } from "@/layouts/SidebarLayout";
import { apiService } from "@/lib/api";
import { wsManager } from "@/lib/websocket";
import { useChatStoreSync } from "@/stores/chatStore";
import { useHoloCardModalStore } from "@/stores/holoCardModalStore";
import {
  OnboardingPhase,
  useOnboardingPhaseStore,
} from "@/stores/onboardingStore";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { useUIStoreSidebar } from "@/stores/uiStore";

const HeaderSidebarTrigger = () => {
  return (
    <div className="">
      <CustomSidebarTrigger />
    </div>
  );
};

export default function MainLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
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
  const {
    open: isHoloCardModalOpen,
    openModal: openHoloCardModal,
    closeModal: closeHoloCardModal,
  } = useHoloCardModalStore();
  const { phase: onboardingPhase, setPhase } = useOnboardingPhaseStore();

  // Check if user needs onboarding
  useOnboardingGuard();
  useBackgroundSync();
  useOAuthSuccessToast(); // Global OAuth success/error toast handling

  // Determine visibility of onboarding UI elements:
  const hasCompletedInitialOnboarding = user.onboarding?.completed === true;

  // Initialize onboarding phase from backend on mount
  useEffect(() => {
    const initializePhase = async () => {
      if (!hasCompletedInitialOnboarding) return;

      try {
        const data = await apiService.get<{ phase?: string }>(
          "/onboarding/personalization",
          { silent: true },
        );

        if (data.phase) {
          console.log("[MainLayout] Initialized phase from API:", data.phase);
          setPhase(data.phase as OnboardingPhase);
        }
      } catch (error) {
        console.error("[MainLayout] Failed to fetch initial phase:", error);
      }
    };

    initializePhase();
  }, [hasCompletedInitialOnboarding, setPhase]);

  // Listen for WebSocket phase updates
  useEffect(() => {
    const handlePhaseUpdate = (message: unknown) => {
      if (isOnboardingPhaseUpdateMessage(message) && message.data?.phase) {
        setPhase(message.data.phase);
      }
    };

    console.log(
      "[MainLayout] Registering WebSocket listener for phase updates",
    );
    wsManager.on("onboarding_phase_update", handlePhaseUpdate);

    return () => {
      wsManager.off("onboarding_phase_update", handlePhaseUpdate);
    };
  }, [setPhase]);

  // Visibility logic based on phase from store
  const shouldShowPersonalizationCard =
    hasCompletedInitialOnboarding &&
    onboardingPhase &&
    (onboardingPhase === OnboardingPhase.PERSONALIZATION_PENDING ||
      onboardingPhase === OnboardingPhase.PERSONALIZATION_COMPLETE);

  const shouldShowGettingStartedCard =
    hasCompletedInitialOnboarding &&
    onboardingPhase &&
    (onboardingPhase === OnboardingPhase.GETTING_STARTED ||
      onboardingPhase === OnboardingPhase.COMPLETED);

  useChatStoreSync();

  // Auto-close sidebar on mobile when pathname changes
  useEffect(() => {
    if (isMobile && isMobileOpen) setMobileOpen(false);
  }, [isMobile, isMobileOpen, setMobileOpen]);

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
          className="relative flex min-h-screen w-full dark"
          style={{ touchAction: "pan-y" }}
          ref={dragRef}
        >
          <SidebarLayout>
            <Sidebar />
          </SidebarLayout>

          <SidebarInset className="flex h-screen flex-col bg-primary-bg">
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

          <RightSidebar isOpen={rightSidebarOpen} variant={rightSidebarVariant}>
            {rightSidebarContent}
          </RightSidebar>
        </div>

        {/* Global Command Menu */}
        <CommandMenu open={commandMenuOpen} onOpenChange={setCommandMenuOpen} />

        {/* Onboarding Components */}
        <HoloCardModal
          isOpen={isHoloCardModalOpen}
          onClose={closeHoloCardModal}
        />

        {/* Onboarding assistance cards - shown after completing initial onboarding */}
        {(shouldShowPersonalizationCard || shouldShowGettingStartedCard) && (
          <div
            className={`fixed z-40 w-70 space-y-3 overflow-hidden ${pathname === "/integrations" ? "right-4 bottom-16" : "right-4 bottom-4"} `}
          >
            {shouldShowPersonalizationCard && (
              <ContextGatheringLoader onComplete={openHoloCardModal} />
            )}
            {/* {shouldShowGettingStartedCard && <OnboardingStepsCard />} */}
          </div>
        )}
      </SidebarProvider>
    </TooltipProvider>
  );
}
