"use client";

import { Button } from "@heroui/button";
import { Cancel01Icon } from "@icons";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";

import {
  useCloseRightSidebar,
  useRightSidebarState,
} from "@/stores/layoutStore";

/**
 * The right sidebar's portal target. Pages don't push elements into a store;
 * they mount a `<RightSidebarPanel>` and it portals into whichever chrome the
 * current mode renders. Exposed through context rather than `getElementById`
 * so a panel that mounts alongside the slot still finds it once it exists.
 */
const RightSidebarSlotContext = createContext<HTMLElement | null>(null);

const SlotSetterContext = createContext<
  ((element: HTMLElement | null) => void) | null
>(null);

export const useRightSidebarSlot = () => useContext(RightSidebarSlotContext);

export function RightSidebarSlotProvider({
  children,
}: Readonly<{ children: ReactNode }>) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);

  return (
    <SlotSetterContext.Provider value={setSlot}>
      <RightSidebarSlotContext.Provider value={slot}>
        {children}
      </RightSidebarSlotContext.Provider>
    </SlotSetterContext.Provider>
  );
}

const SLOT_CLASSNAME = "min-h-0 flex-1 overflow-y-auto overscroll-contain";

/**
 * The single portal target. Exactly one is rendered at a time — inside whichever
 * chrome the current mode uses — so the portalled panel moves with the mode.
 */
function Slot({ className = SLOT_CLASSNAME }: { className?: string }) {
  const setSlot = useContext(SlotSetterContext);
  return (
    <div
      id="right-sidebar-slot"
      className={className}
      ref={(node) => {
        setSlot?.(node);
      }}
    />
  );
}

/**
 * Renders the right sidebar chrome for the current mode and hosts the portal
 * slot. Reads the layout store directly — the main layout just mounts it.
 */
export default function RightSidebarSlot() {
  const { isOpen, mode } = useRightSidebarState();
  const close = useCloseRightSidebar();

  const sidebarWidth = "350px";
  const artifactWidth = "clamp(520px, 46vw, 980px)";

  // Close sidebar on Escape key
  useEffect(() => {
    if (!isOpen || typeof window === "undefined") return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, close]);

  const closeButton = (
    <div className="flex w-full items-center justify-end px-3 pt-3 pb-1">
      <Button
        onPress={close}
        variant="light"
        isIconOnly
        size="sm"
        aria-label="Close"
      >
        <Cancel01Icon className="size-4" />
      </Button>
    </div>
  );

  const isSheet = mode === "sheet";
  const isArtifact = mode === "artifact";
  const isSidebar = mode === "sidebar";
  const sheetOpen = isSheet && isOpen;

  return (
    <>
      {/* Sheet mode (overlay) — always mounted so translateX(100%) is painted
          before the first open, giving CSS transitions a starting state. */}
      <aside
        className="absolute top-0 right-0 z-50 flex h-full min-h-0 flex-col overflow-hidden bg-secondary-bg transition-transform duration-300 ease-in-out"
        style={{
          width: "380px",
          transform: sheetOpen ? "translateX(0)" : "translateX(100%)",
          pointerEvents: sheetOpen ? "auto" : "none",
        }}
        aria-hidden={!sheetOpen}
      >
        {sheetOpen && closeButton}
        {isSheet ? <Slot /> : <div className={SLOT_CLASSNAME} />}
      </aside>

      {/* Artifact mode */}
      {isArtifact && (
        <aside
          className="relative flex h-full min-h-0 shrink-0 flex-col border-l border-zinc-800 bg-zinc-950 transition-[width,min-width] duration-300 ease-in-out"
          style={{
            width: isOpen ? artifactWidth : "0px",
            minWidth: isOpen ? artifactWidth : "0px",
            overflow: "hidden",
          }}
        >
          <Slot className="flex h-full min-h-0 flex-col overflow-hidden" />
        </aside>
      )}

      {/* Sidebar mode */}
      {isSidebar && (
        <aside
          className="relative flex min-h-0 shrink-0 flex-col bg-secondary-bg transition-[width,min-width] duration-300 ease-in-out"
          style={{
            width: isOpen ? sidebarWidth : "0px",
            minWidth: isOpen ? sidebarWidth : "0px",
            overflow: "hidden",
          }}
        >
          {isOpen && closeButton}
          <Slot />
        </aside>
      )}
    </>
  );
}
