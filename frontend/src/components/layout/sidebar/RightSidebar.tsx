"use client";

import { ReactNode } from "react";

import { Cancel01Icon } from "@/components/shared/icons";
import { useRightSidebar } from "@/stores/rightSidebarStore";

interface RightSidebarProps {
  children: ReactNode;
  isOpen: boolean;
}

export default function RightSidebar({ children, isOpen }: RightSidebarProps) {
  const close = useRightSidebar((state) => state.close);

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
          <button
            onClick={close}
            className="cursor-pointer rounded-lg p-2 text-zinc-400 transition-colors hover:bg-zinc-800/50 hover:text-zinc-200"
            aria-label="Close"
          >
            <Cancel01Icon className="size-4" />
          </button>
        </div>
      )}
      {children}
    </aside>
  );
}
