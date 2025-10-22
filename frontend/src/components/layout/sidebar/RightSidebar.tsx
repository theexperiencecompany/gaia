"use client";

import { ReactNode } from "react";

interface RightSidebarProps {
  children: ReactNode;
  isOpen: boolean;
}

export default function RightSidebar({ children, isOpen }: RightSidebarProps) {
  return (
    <aside
      className="relative flex flex-col border-l border-zinc-800 bg-[#141414] transition-all duration-300 ease-in-out"
      style={{
        width: isOpen ? "300px" : "0px",
        minWidth: isOpen ? "300px" : "0px",
        overflow: isOpen ? "visible" : "hidden",
      }}
    >
      {children}
    </aside>
  );
}
