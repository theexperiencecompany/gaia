"use client";

import { Button } from "@heroui/button";
import { Cancel01Icon } from "@icons";
import { type ReactNode, useEffect } from "react";
import {
  type RightSidebarVariant,
  useRightSidebar,
} from "@/stores/rightSidebarStore";

interface RightSidebarProps {
  children: ReactNode;
  isOpen: boolean;
  variant?: RightSidebarVariant;
}

export default function RightSidebar({
  children,
  isOpen,
  variant = "sheet",
}: RightSidebarProps) {
  const close = useRightSidebar((state) => state.close);
  const sidebarWidth = "350px";
  const artifactWidth = "clamp(520px, 46vw, 980px)";

  // Close sidebar on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close();
      }
    };
    if (typeof window !== "undefined")
      window.addEventListener("keydown", handleKeyDown);
    return () => {
      if (typeof window !== "undefined")
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

  if (variant === "artifact") {
    return (
      <aside
        className="relative flex h-full min-h-0 shrink-0 flex-col border-l border-zinc-800 bg-zinc-950 transition-[width,min-width] duration-300 ease-in-out"
        style={{
          width: isOpen ? artifactWidth : "0px",
          minWidth: isOpen ? artifactWidth : "0px",
          overflow: "hidden",
        }}
      >
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
          {children}
        </div>
      </aside>
    );
  }

  if (variant === "sidebar") {
    return (
      <aside
        className="relative flex min-h-0 shrink-0 flex-col bg-secondary-bg transition-[width,min-width] duration-300 ease-in-out"
        style={{
          width: isOpen ? sidebarWidth : "0px",
          minWidth: isOpen ? sidebarWidth : "0px",
          overflow: "hidden",
        }}
      >
        {isOpen && closeButton}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {children}
        </div>
      </aside>
    );
  }

  // Sheet variant (overlay)
  return (
    <aside
      className="absolute top-0 right-0 z-50 flex h-full min-h-0 flex-col overflow-hidden bg-secondary-bg transition-transform duration-300 ease-in-out"
      style={{
        width: "380px",
        transform: isOpen ? "translateX(0)" : "translateX(100%)",
      }}
    >
      {isOpen && closeButton}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {children}
      </div>
    </aside>
  );
}
