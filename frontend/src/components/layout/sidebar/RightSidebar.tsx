"use client";

import { Button } from "@heroui/button";
import { ReactNode, useEffect } from "react";

import { Cancel01Icon } from "@/components/shared/icons";
import { useRightSidebar } from "@/stores/rightSidebarStore";

interface RightSidebarProps {
  children: ReactNode;
  isOpen: boolean;
  variant?: "overlay" | "push";
}

export default function RightSidebar({
  children,
  isOpen,
  variant = "overlay",
}: RightSidebarProps) {
  const close = useRightSidebar((state) => state.close);

  // Close sidebar on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, close]);

  if (variant === "push") {
    return (
      <aside
        className="relative flex flex-col border-l border-zinc-800 bg-[#141414] transition-all duration-300 ease-in-out"
        style={{
          width: isOpen ? "350px" : "0px",
          minWidth: isOpen ? "350px" : "0px",
          overflow: isOpen ? "visible" : "hidden",
        }}
      >
        {isOpen && (
          <div className="flex w-full items-end justify-end px-6 pt-4 pb-0">
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
        )}
        <div className="flex-1 overflow-auto">{children}</div>
      </aside>
    );
  }

  return (
    <aside
      className="absolute top-0 right-0 z-50 flex h-full flex-col border-l border-zinc-800 bg-[#141414] shadow-2xl transition-transform duration-300 ease-in-out"
      style={{
        width: "350px",
        transform: isOpen ? "translateX(0)" : "translateX(100%)",
      }}
    >
      {isOpen && (
        <div className="flex w-full items-end justify-end px-6 pt-4 pb-0">
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
      )}
      <div className="flex-1 overflow-auto">{children}</div>
    </aside>
  );
}
