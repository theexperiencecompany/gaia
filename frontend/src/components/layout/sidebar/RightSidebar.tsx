"use client";

import { ReactNode, useEffect } from "react";

import { Cancel01Icon } from "@/components/shared/icons";
import { useRightSidebar } from "@/stores/rightSidebarStore";
import { Button } from "@heroui/button";

interface RightSidebarProps {
  children: ReactNode;
  isOpen: boolean;
}

export default function RightSidebar({ children, isOpen }: RightSidebarProps) {
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
      {children}
    </aside>
  );
}
