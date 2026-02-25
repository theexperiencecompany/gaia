"use client";

import { Tab, Tabs } from "@heroui/tabs";
import { AnimatePresence, m } from "motion/react";
import { useEffect, useState } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const wfEase = [0.32, 0.72, 0, 1] as const;

type TriggerTab = "schedule" | "trigger" | "manual";

interface DemoTriggerTabsProps {
  activeTab: TriggerTab;
  showContent: boolean;
  triggerType?: "schedule" | "trigger";
}

const DEMO_TRIGGERS = [
  {
    slug: "gmail_new_message",
    name: "New Gmail Message",
    description: "Triggers when a new email arrives",
    integration_id: "gmail",
  },
  {
    slug: "slack_new_message",
    name: "New Slack Message",
    description: "Triggers on new messages in channels",
    integration_id: "slack",
  },
  {
    slug: "github_commit_event",
    name: "New Commit",
    description: "Triggers on push events to repositories",
    integration_id: "github",
  },
  {
    slug: "calendar_event_starting_soon",
    name: "Event Starting Soon",
    description: "Triggers before calendar events",
    integration_id: "googlecalendar",
  },
  {
    slug: "linear_issue_created",
    name: "New Linear Issue",
    description: "Triggers when issues are created",
    integration_id: "linear",
  },
];

export default function DemoTriggerTabs({
  activeTab: initialTab,
  showContent,
}: DemoTriggerTabsProps) {
  const [selectedTab, setSelectedTab] = useState<TriggerTab>(initialTab);

  useEffect(() => {
    setSelectedTab(initialTab);
  }, [initialTab]);

  return (
    <div className="space-y-2.5">
      <div className="flex items-start gap-3">
        <div className="mt-2.5 flex min-w-26 items-center gap-1.5 text-sm font-medium text-zinc-400">
          <span className="text-nowrap">When to Run</span>
        </div>

        <Tabs
          aria-label="Workflow trigger configuration"
          selectedKey={selectedTab}
          onSelectionChange={(key) => setSelectedTab(key as TriggerTab)}
          classNames={{
            tabList: "flex flex-row",
            base: "flex items-start",
            tabWrapper: "w-full",
            panel: "min-w-full",
          }}
        >
          <Tab key="schedule" title="Schedule" />
          <Tab key="trigger" title="Trigger" />
          <Tab key="manual" title="Manual" />
        </Tabs>
      </div>

      <AnimatePresence mode="wait">
        {/* Schedule content */}
        {showContent && selectedTab === "schedule" && (
          <m.div
            key="schedule-content"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease: wfEase }}
            className="overflow-hidden"
          >
            <div className="flex items-center gap-3 rounded-lg bg-zinc-800/60 px-3 py-2.5">
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/15 text-xs font-medium text-primary">
                9
              </div>
              <div>
                <p className="text-sm font-medium text-zinc-300">
                  Every day at 9:00 AM
                </p>
                <p className="text-xs text-zinc-600">
                  0 9 * * * &middot; America/New_York
                </p>
              </div>
            </div>
          </m.div>
        )}

        {/* Trigger content - staggered list */}
        {showContent && selectedTab === "trigger" && (
          <m.div
            key="trigger-content"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease: wfEase }}
            className="overflow-hidden"
          >
            <div className="space-y-1">
              {DEMO_TRIGGERS.map((trigger, i) => (
                <m.div
                  key={trigger.slug}
                  initial={{ opacity: 0, x: -12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{
                    delay: i * 0.08,
                    duration: 0.25,
                    ease: wfEase,
                  }}
                  className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 hover:bg-zinc-800/40"
                >
                  <div className="shrink-0">
                    {getToolCategoryIcon(trigger.integration_id, {
                      width: 20,
                      height: 20,
                      showBackground: false,
                    })}
                  </div>
                  <div className="flex flex-col">
                    <span className="text-sm text-zinc-200">
                      {trigger.name}
                    </span>
                    <span className="text-xs text-zinc-500">
                      {trigger.description}
                    </span>
                  </div>
                </m.div>
              ))}
            </div>
          </m.div>
        )}

        {/* Manual content */}
        {showContent && selectedTab === "manual" && (
          <m.div
            key="manual-content"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease: wfEase }}
            className="overflow-hidden"
          >
            <p className="text-sm text-zinc-500">
              This workflow will be triggered manually when you run it.
            </p>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}
