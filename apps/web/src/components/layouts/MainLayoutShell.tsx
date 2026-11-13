"use client";

import { useDrag } from "@use-gesture/react";
import nextDynamic from "next/dynamic";
import { type ReactNode, useEffect, useRef, useState } from "react";
import HeaderManager from "@/components/layout/headers/HeaderManager";
import StatusBanner from "@/components/layout/StatusBanner";
import Sidebar from "@/components/layout/sidebar/MainSidebar";
import RightSidebarSlot, {
  RightSidebarSlotProvider,
} from "@/components/layout/sidebar/RightSidebarSlot";
import { PaidShellOverlays } from "@/components/layouts/PaidShellOverlays";
import {
  MAIN_CONTENT_ID,
  SkipToContentLink,
} from "@/components/navigation/SkipToContentLink";
import SuspenseLoader from "@/components/shared/SuspenseLoader";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { UNPAID_APP_ROUTES } from "@/features/auth/constants";
import { useOnboardingGuard } from "@/features/auth/hooks/useOnboardingGuard";
import { useFocusHeartbeat } from "@/features/presence/hooks/useFocusHeartbeat";
import { useAppSessionEnabled } from "@/features/pricing/hooks/useEntitlement";
import { useDeployment } from "@/features/settings/hooks/useSetupStatus";
import { useIsMobile } from "@/hooks/ui/useMobile";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { useBackgroundSync } from "@/hooks/useBackgroundSync";
import { useElectron } from "@/hooks/useElectron";
import { usePathname } from "@/i18n/navigation";
import ProvidersLayout from "@/layouts/ProvidersLayout";
import SidebarLayout, { CustomSidebarTrigger } from "@/layouts/SidebarLayout";
import { cn } from "@/lib/utils";
import { useChatStoreSync } from "@/stores/chatStore";
import { useLayoutSidebar } from "@/stores/layoutStore";

const UpgradeModal = nextDynamic(
  () =>
    import("@/features/pricing/components/UpgradeModal").then((m) => ({
      default: m.UpgradeModal,
    })),
  { ssr: false },
);
interface HeaderSidebarTriggerProps {
  className?: string;
}

const HeaderSidebarTrigger = ({ className }: HeaderSidebarTriggerProps) => {
  return (
    <div className={className}>
      {/* No hover background: the trigger sits in the native title bar next
          to the traffic lights, so a hover box makes it read heavier and
          slightly off-centre. The tooltip remains as the affordance. */}
      <CustomSidebarTrigger className="hover:bg-transparent" />
    </div>
  );
};

interface ShellTitleBarProps {
  collapsed: boolean;
  /** The sidebar trigger and route header, mounted only with the paid session. */
  showControls: boolean;
}

const ShellTitleBar = ({ collapsed, showControls }: ShellTitleBarProps) => {
  const { isElectron } = useElectron();
  const { isMac } = usePlatform();

  // On macOS desktop, the top-left corner belongs to the hiddenInset window
  // controls once the sidebar collapses (offcanvas), so the re-open trigger
  // must clear them horizontally.
  const clearTrafficLights = isElectron && isMac && collapsed;

  return (
    <header
      className={cn(
        // Desktop only: the 44px band centres the 36px controls at y=22,
        // the macOS hiddenInset traffic-light centre (y=16, 12px tall).
        isElectron
          ? "flex h-11 shrink-0 items-center justify-between px-2"
          : "flex shrink-0 items-center justify-between p-2",
        clearTrafficLights && "pl-20",
        // Collapsed sidebar no longer supplies the visual separation,
        // so the top bar takes the border itself.
        isElectron && collapsed && "border-b border-zinc-800",
        // Makes the top bar the macOS hiddenInset drag region; buttons
        // opt back out via the .electron-drag descendant rule in globals.css.
        isElectron && isMac && "electron-drag",
      )}
    >
      {showControls && (
        <>
          <HeaderSidebarTrigger
            // The collapsed border eats 1px of the header's content box,
            // which centres the 36px trigger 0.5px high (21.5 vs the
            // lights' 22). Nudge it back down so it sits pixel-perfect.
            className={
              isElectron && collapsed ? "translate-y-[0.5px]" : undefined
            }
          />
          <HeaderManager />
        </>
      )}
    </header>
  );
};

export function MainLayoutShell({ children }: { children: ReactNode }) {
  const { isOpen, isMobileOpen, setOpen, setMobileOpen } = useLayoutSidebar();
  const isMobile = useIsMobile();
  const [defaultOpen, setDefaultOpen] = useState(true);
  const dragRef = useRef<HTMLDivElement>(null);
  const billingEnabled = useDeployment().bills;
  const pathname = usePathname();
  // The paid app (sidebar, header, sync, the page itself) mounts only for an
  // account allowed to use it; until then only the routes an unpaid account
  // lives on render, so nothing behind the paywall is ever requested.
  const appSessionEnabled = useAppSessionEnabled();
  const showPage = appSessionEnabled || UNPAID_APP_ROUTES.includes(pathname);
  // Check if user needs onboarding
  useOnboardingGuard();
  useBackgroundSync(appSessionEnabled);
  useFocusHeartbeat(appSessionEnabled);

  useChatStoreSync();

  // Auto-close sidebar on mobile when pathname changes
  useEffect(() => {
    if (isMobile && isMobileOpen) setMobileOpen(false);
  }, [isMobile, isMobileOpen, setMobileOpen]);

  useEffect(() => {
    if (isMobile) setDefaultOpen(false);
    else setDefaultOpen(true);
  }, [isMobile]);

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
      if (tap) return;

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
      // Swipes only open the mobile sidebar; on desktop the listener only swallows clicks.
      enabled: isMobile,
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
        <RightSidebarSlotProvider>
          <SidebarProvider
            open={currentOpen}
            onOpenChange={handleOpenChange}
            defaultOpen={defaultOpen}
          >
            <div className="relative flex h-screen w-full dark" ref={dragRef}>
              <SkipToContentLink />
              {appSessionEnabled && (
                <SidebarLayout>
                  <Sidebar />
                </SidebarLayout>
              )}

              <SidebarInset className="flex h-screen min-w-0 w-auto flex-col bg-primary-bg">
                {/* Tapping anywhere outside the mobile sidebar dismisses it via
                  the Sheet's own modal overlay (see ui/sidebar), so the shell
                  needs no click handler of its own here. */}
                <ShellTitleBar
                  collapsed={!currentOpen}
                  showControls={appSessionEnabled}
                />
                {/* Below the title bar so a visible banner never shifts the
                  window controls out of alignment with the traffic lights. */}
                <StatusBanner />
                {/* SidebarInset is the page's one main landmark. */}
                <div
                  id={MAIN_CONTENT_ID}
                  className="flex flex-1 flex-col overflow-hidden"
                >
                  {showPage ? children : <SuspenseLoader fullHeight />}
                </div>
              </SidebarInset>

              <RightSidebarSlot />
            </div>

            {/* The one Pro upsell modal — non-dismissible when opened by
              enforcement (402 subscription_required), dismissible when the
              user opened it themselves. Nothing to sell where billing is off. */}
            {billingEnabled && <UpgradeModal />}

            {appSessionEnabled && <PaidShellOverlays />}
          </SidebarProvider>
        </RightSidebarSlotProvider>
      </TooltipProvider>
    </ProvidersLayout>
  );
}
