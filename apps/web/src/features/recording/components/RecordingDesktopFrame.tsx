"use client";

import {
  BubbleChatAddIcon,
  BubbleChatQuestionIcon,
  Calendar03Icon,
  CheckListIcon,
  ConnectIcon,
  DashboardSquare02Icon,
  MessageMultiple02Icon,
  PinIcon,
  SearchIcon,
  SidebarLeft01Icon,
  Target02Icon,
  ZapIcon,
} from "@icons";
import Image from "next/image";
import type { ReactNode } from "react";

/* ------------------------------------------------------------------ */
/*  Static sidebar + header chrome for desktop recording viewport     */
/*  Mirrors the real GAIA desktop UI layout pixel-for-pixel.          */
/* ------------------------------------------------------------------ */

// Fake chat list entries for the sidebar
const FAKE_CHATS: { section: string; items: string[] }[] = [
  {
    section: "Today",
    items: [
      "Series A investor prep",
      "Q1 metrics dashboard",
      "Weekly team standup notes",
    ],
  },
  {
    section: "Yesterday",
    items: ["Product roadmap review", "Customer onboarding flow"],
  },
  {
    section: "Previous 7 days",
    items: [
      "Hiring plan for engineering",
      "Competitive analysis update",
      "Marketing campaign ideas",
      "Bug triage — auth flow",
    ],
  },
];

// Nav buttons matching SidebarTopButtons
const NAV_ITEMS = [
  { icon: DashboardSquare02Icon, label: "Dashboard" },
  { icon: Calendar03Icon, label: "Calendar" },
  { icon: Target02Icon, label: "Goals" },
  { icon: CheckListIcon, label: "Todos" },
  { icon: ConnectIcon, label: "Integrations" },
  { icon: ZapIcon, label: "Workflows" },
  { icon: MessageMultiple02Icon, label: "Chats", active: true },
];

function StaticSidebar() {
  return (
    <div
      className="flex h-full shrink-0 flex-col border-none bg-[#1a1a1a]"
      style={{ width: 260 }}
    >
      {/* Logo header */}
      <div className="flex items-center px-4 pt-4 pb-2">
        <Image
          src="/images/logos/text_w_logo_white.webp"
          alt="GAIA"
          width={100}
          height={30}
          className="object-contain"
          priority
        />
      </div>

      {/* Nav buttons */}
      <div className="flex flex-col gap-0.5 px-2 pt-2 pb-3">
        {NAV_ITEMS.map((item) => (
          <div
            key={item.label}
            className={`flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-sm ${
              item.active ? "bg-zinc-800 text-zinc-300" : "text-zinc-400"
            }`}
          >
            <div className="flex w-[17px] min-w-[17px] items-center justify-center">
              <item.icon width={18} height={18} />
            </div>
            <span className="truncate">{item.label}</span>
          </div>
        ))}
      </div>

      {/* Chat list */}
      <div className="flex-1 overflow-hidden px-2">
        {FAKE_CHATS.map((group) => (
          <div key={group.section} className="mb-2">
            <div className="px-2 pb-1 text-xs font-normal text-zinc-600">
              {group.section}
            </div>
            <div className="flex flex-col gap-0.5">
              {group.items.map((name, i) => (
                <div
                  key={name}
                  className={`flex items-center rounded-xl px-2 py-1.5 text-sm ${
                    /* Highlight the first chat item as "active" */
                    group.section === "Today" && i === 0
                      ? "bg-zinc-800 text-zinc-300"
                      : "text-zinc-400"
                  }`}
                >
                  <span className="truncate">{name}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Footer: user + support */}
      <div className="relative z-[4] p-2 px-3 pb-3">
        {/* User row */}
        <div className="flex w-full items-center gap-3 rounded-xl px-2 py-2">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-zinc-700">
            <span className="text-xs text-zinc-300">A</span>
          </div>
          <div className="flex flex-col items-start -space-y-0.5">
            <span className="text-sm text-zinc-300">Aryan</span>
            <span className="text-[11px] text-zinc-500">GAIA Pro</span>
          </div>
        </div>

        {/* Contact support */}
        <div className="flex w-full justify-center pt-1">
          <div className="flex h-7 w-full items-center justify-center gap-1.5 rounded-full bg-zinc-800/60 text-sm text-zinc-300">
            <BubbleChatQuestionIcon width={17} height={17} />
            <span>Contact Support</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function StaticHeader() {
  return (
    <div className="flex w-full shrink-0 items-center justify-between p-2">
      {/* Left: sidebar toggle */}
      <div className="rounded-xl p-1 text-zinc-400">
        <SidebarLeft01Icon className="size-5" />
      </div>

      {/* Right: action buttons */}
      <div className="flex items-center">
        <div className="rounded-xl p-1 text-zinc-400">
          <SearchIcon className="size-5" width={20} height={20} />
        </div>
        <div className="rounded-xl p-1 text-zinc-400">
          <PinIcon className="size-5" width={20} height={20} />
        </div>
        <div className="rounded-xl p-1 text-zinc-400">
          <BubbleChatAddIcon className="size-5" width={20} height={20} />
        </div>
      </div>
    </div>
  );
}

interface RecordingDesktopFrameProps {
  children: ReactNode;
}

export default function RecordingDesktopFrame({
  children,
}: RecordingDesktopFrameProps) {
  return (
    <div className="flex h-full w-full" style={{ backgroundColor: "#111111" }}>
      <StaticSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <StaticHeader />
        {children}
      </div>
    </div>
  );
}
