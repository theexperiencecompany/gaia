"use client";

import { Tab, Tabs } from "@heroui/tabs";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useState } from "react";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";

import { Arcade } from "./versions/Arcade";
import { MissionControl } from "./versions/MissionControl";
import { ObsidianEditorial } from "./versions/ObsidianEditorial";
import { TheTicket } from "./versions/TheTicket";

type VersionKey = "mission" | "obsidian" | "arcade" | "ticket";

const VERSIONS: {
  key: VersionKey;
  label: string;
  blurb: string;
  Component: () => React.ReactElement;
}[] = [
  {
    key: "mission",
    label: "Mission Control",
    blurb: "Telemetry dashboard",
    Component: MissionControl,
  },
  {
    key: "obsidian",
    label: "Obsidian Editorial",
    blurb: "Luxury invitation",
    Component: ObsidianEditorial,
  },
  {
    key: "arcade",
    label: "Arcade",
    blurb: "Gamified quest",
    Component: Arcade,
  },
  {
    key: "ticket",
    label: "The Ticket",
    blurb: "Tear-off ticket",
    Component: TheTicket,
  },
];

export default function ReferralDemoBody() {
  const [active, setActive] = useState<VersionKey>("mission");
  const current = VERSIONS.find((v) => v.key === active) ?? VERSIONS[0];
  const ActiveComponent = current.Component;

  return (
    <LazyMotionProvider>
      <div className="flex h-full min-h-0 flex-col bg-[#111111]">
        {/* Version switcher */}
        <header className="shrink-0 border-b border-zinc-900 bg-[#0d0d0e]/80 px-4 py-3 backdrop-blur-xl">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
            <div>
              <h1 className="text-sm font-semibold text-zinc-100">
                Referral share pages
              </h1>
              <p className="text-xs text-zinc-500">{current.blurb}</p>
            </div>
            <Tabs
              aria-label="Referral page version"
              selectedKey={active}
              onSelectionChange={(k) => setActive(k as VersionKey)}
              variant="solid"
              radius="full"
              classNames={{
                tabList: "bg-zinc-900 p-1",
                cursor: "bg-zinc-700",
                tab: "px-3 h-8 data-[hover-unselected=true]:opacity-100",
                tabContent:
                  "text-xs font-medium text-zinc-500 group-data-[selected=true]:text-zinc-100",
              }}
            >
              {VERSIONS.map((v) => (
                <Tab key={v.key} title={v.label} />
              ))}
            </Tabs>
          </div>
        </header>

        {/* Active version */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <AnimatePresence mode="wait">
            <m.div
              key={active}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
              className="min-h-full"
            >
              <ActiveComponent />
            </m.div>
          </AnimatePresence>
        </div>
      </div>
    </LazyMotionProvider>
  );
}
