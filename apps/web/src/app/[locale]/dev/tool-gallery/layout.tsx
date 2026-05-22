"use client";

import { TOOL_FIXTURES } from "@shared/chat";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { JSX, ReactNode } from "react";

export default function ToolGalleryLayout({
  children,
}: {
  children: ReactNode;
}): JSX.Element {
  const pathname = usePathname();
  const segments = pathname.split("/");
  const activeTool = segments[segments.length - 1];
  const isActive = (toolName: string) =>
    activeTool === toolName || pathname.endsWith(`/${toolName}`);

  return (
    <div className="flex h-full bg-primary-bg">
      <nav className="w-56 flex-shrink-0 overflow-y-auto border-r border-zinc-800/60 py-4">
        <Link
          href="/dev/tool-gallery"
          className="mb-3 block px-4 text-[10px] font-semibold uppercase tracking-widest text-zinc-500 hover:text-zinc-400"
        >
          Tool Gallery
        </Link>
        {TOOL_FIXTURES.map((fixture) => (
          <Link
            key={fixture.toolName}
            href={`/dev/tool-gallery/${fixture.toolName}`}
            className={`block truncate px-4 py-1.5 text-sm transition-colors ${
              isActive(fixture.toolName)
                ? "bg-zinc-800 font-medium text-zinc-100"
                : "text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-200"
            }`}
          >
            {fixture.label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}
