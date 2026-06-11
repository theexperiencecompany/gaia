"use client";

import { Divider } from "@heroui/divider";
import { Skeleton } from "@heroui/skeleton";
import { Tab, Tabs } from "@heroui/tabs";
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
import type { ComponentType } from "react";
import { useCallback, useEffect, useState } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type { MemoryOverviewResponse } from "@/features/memory/api/types";
import { CoreDocuments } from "@/features/memory/components/CoreDocuments";
import { MemoryGraphView } from "@/features/memory/components/MemoryGraphView";
import { MemoryList } from "@/features/memory/components/MemoryList";
import { MemoryTimeline } from "@/features/memory/components/MemoryTimeline";
import { MemoryTree } from "@/features/memory/components/MemoryTree";

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
      <div className="flex items-center rounded-2xl bg-zinc-800 px-5 py-4">
        {stats.map((stat, index) => (
          <div key={stat.label} className="flex items-center">
            {index > 0 && (
              <Divider
                orientation="vertical"
                className="mx-6 h-8 bg-zinc-700/50"
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
        variant="light"
        selectedKey={selectedTab}
        onSelectionChange={(key) => setSelectedTab(key as string)}
      >
        <Tab
          key="folders"
          title={<TabTitle icon={Folder01Icon} label="Folders" />}
        />
        <Tab
          key="graph"
          title={<TabTitle icon={NeuralNetworkIcon} label="Graph" />}
        />
        <Tab
          key="journal"
          title={<TabTitle icon={BookOpen01Icon} label="Journal" />}
        />
        <Tab
          key="documents"
          title={<TabTitle icon={Note01Icon} label="Documents" />}
        />
        <Tab key="all" title={<TabTitle icon={ListViewIcon} label="All" />} />
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
