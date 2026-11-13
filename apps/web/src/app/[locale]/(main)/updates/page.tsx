"use client";

import type { UpdateFilter } from "@shared/api/generated";
import { useEffect, useState } from "react";
import UpdatesHeader from "@/components/layout/headers/UpdatesHeader";
import { NotificationConnectBanner } from "@/features/notification/components/NotificationConnectBanner";
import { UpdatesFeed } from "@/features/updates/components/UpdatesFeed";
import { useMarkUpdatesSeen } from "@/features/updates/hooks/useMarkUpdatesSeen";
import { useHeader } from "@/hooks/layout/useHeader";
import { track } from "@/lib/analytics";

export default function UpdatesPage() {
  const [filter, setFilter] = useState<UpdateFilter>("all");
  const { setHeader } = useHeader();

  useMarkUpdatesSeen();

  useEffect(() => {
    track("delivery:updates_viewed", {});
  }, []);

  useEffect(() => {
    setHeader(<UpdatesHeader filter={filter} onFilterChange={setFilter} />);
    return () => setHeader(null);
  }, [filter, setHeader]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-primary-bg">
      <div className="shrink-0 px-6 pt-6">
        <NotificationConnectBanner variant="full" />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <UpdatesFeed filter={filter} />
      </div>
    </div>
  );
}
