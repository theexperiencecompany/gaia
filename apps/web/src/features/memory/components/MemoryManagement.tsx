"use client";

import { Separator, Skeleton, Tabs } from "@heroui/react";
import {
  AiBrain01Icon,
  BookOpen01Icon,
  Calendar01Icon,
  Database01Icon,
  Folder01Icon,
  ListViewIcon,
  NeuralNetworkIcon,
  Note01Icon,
} from "@icons";
import type { MemoryOverviewResponse } from "@shared/api/generated";
import dynamic from "next/dynamic";
import type { ComponentType } from "react";
import { useCallback, useEffect, useState } from "react";
import { separatorVariants } from "@/components/shared/controlVariants";
import { shapeVariants } from "@/components/shared/shape";
import { tabsVariants } from "@/components/shared/tabsVariants";
import { memoryApi } from "@/features/memory/api/memoryApi";
import { CoreDocuments } from "@/features/memory/components/CoreDocuments";
import { MemoryDocsBanner } from "@/features/memory/components/MemoryDocsBanner";
import { MemoryList } from "@/features/memory/components/MemoryList";
import { MemoryTimeline } from "@/features/memory/components/MemoryTimeline";
import { MemoryTree } from "@/features/memory/components/MemoryTree";

// The graph view pulls @supermemory/memory-graph + d3 + dagre (~1 MB), but is
// only shown when the "graph" tab is selected. Lazy-load it so the memory page
// doesn't ship the graph stack to users who never open that tab.
const MemoryGraphView = dynamic(
  () =>
    import("@/features/memory/components/MemoryGraphView").then((m) => ({
      default: m.MemoryGraphView,
    })),
  {
    ssr: false,
    loading: () => <Skeleton className="h-[400px] w-full rounded-2xl" />,
  },
);

export interface MemoryManagementProps {
  className?: string;
  autoFetch?: boolean;
}

interface OverviewStat {
  label: string;
  value: number;
  icon: ComponentType<{ className?: string }>;
}

export default function MemoryManagement({
  className = "",
  autoFetch = true,
}: MemoryManagementProps) {
  const [selectedTab, setSelectedTab] = useState("folders");
  const [overview, setOverview] = useState<MemoryOverviewResponse | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);

  const fetchOverview = useCallback(async () => {
    try {
      const response = await memoryApi.getOverview();
      setOverview(response);
    } catch {
      setOverview(null);
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  useEffect(() => {
    if (autoFetch) fetchOverview();
  }, [autoFetch, fetchOverview]);

  const stats: OverviewStat[] = [
    {
      label: "Memories",
      value: overview?.total_memories ?? 0,
      icon: AiBrain01Icon,
    },
    {
      label: "Entities",
      value: overview?.total_entities ?? 0,
      icon: Database01Icon,
    },
    {
      label: "Folders",
      value: overview?.folder_count ?? 0,
      icon: Folder01Icon,
    },
    {
      label: "Journal days",
      value: overview?.episode_count ?? 0,
      icon: Calendar01Icon,
    },
  ];

  return (
    <div className={`flex h-full flex-col gap-4 ${className}`}>
      <MemoryDocsBanner />

      <div className="flex items-center rounded-2xl bg-zinc-800 px-5 py-4">
        {stats.map((stat, index) => (
          <div key={stat.label} className="flex items-center">
            {index > 0 && (
              <Separator
                orientation="vertical"
                className={separatorVariants({
                  surface: "raised",
                  className: "mx-6 h-8",
                })}
              />
            )}
            <div className="flex items-center gap-3">
              <stat.icon className="size-5 shrink-0 text-zinc-500" />
              <div>
                {overviewLoading ? (
                  <Skeleton className="mb-1 h-6 w-10 rounded-lg" />
                ) : (
                  <p className="text-lg font-medium text-white">{stat.value}</p>
                )}
                <p className="text-xs text-zinc-500">{stat.label}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      <Tabs
        className={tabsVariants({ color: "accent" }).base({
          className: shapeVariants({ shape: "pill" }),
        })}
        variant="primary"
        selectedKey={selectedTab}
        onSelectionChange={(key) => setSelectedTab(key as string)}
      >
        <Tabs.ListContainer>
          <Tabs.List aria-label="Memory views">
            <Tabs.Tab id="folders">
              <TabTitle icon={Folder01Icon} label="Folders" />
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="documents">
              <TabTitle icon={Note01Icon} label="Documents" />
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="graph">
              <TabTitle icon={NeuralNetworkIcon} label="Graph" />
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="journal">
              <TabTitle icon={BookOpen01Icon} label="Journal" />
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="all">
              <TabTitle icon={ListViewIcon} label="All" />
              <Tabs.Indicator />
            </Tabs.Tab>
          </Tabs.List>
        </Tabs.ListContainer>
      </Tabs>

      <div className="min-h-0 flex-1">
        {selectedTab === "folders" && <MemoryTree onChanged={fetchOverview} />}
        {selectedTab === "graph" && <MemoryGraphView />}
        {selectedTab === "journal" && <MemoryTimeline />}
        {selectedTab === "documents" && <CoreDocuments />}
        {selectedTab === "all" && <MemoryList onChanged={fetchOverview} />}
      </div>
    </div>
  );
}

interface TabTitleProps {
  icon: ComponentType<{ className?: string }>;
  label: string;
}

function TabTitle({ icon: Icon, label }: TabTitleProps) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="size-4" />
      <span>{label}</span>
    </div>
  );
}
