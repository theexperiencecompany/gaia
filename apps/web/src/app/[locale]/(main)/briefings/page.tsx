"use client";

import { useEffect } from "react";
import BriefingsHeader from "@/components/layout/headers/BriefingsHeader";
import { BriefingArchive } from "@/features/briefing";
import { useHeader } from "@/hooks/layout/useHeader";

export default function BriefingsPage() {
  const { setHeader } = useHeader();

  useEffect(() => {
    setHeader(<BriefingsHeader />);
    return () => {
      setHeader(null);
    };
  }, [setHeader]);

  return (
    <div className="@container min-h-0 flex-1 overflow-y-auto">
      <div className="w-full px-4 pt-3 pb-12 sm:px-6 md:px-8">
        <BriefingArchive />
      </div>
    </div>
  );
}
