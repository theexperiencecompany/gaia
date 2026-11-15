"use client";

import { useEffect } from "react";
import BriefingsHeader from "@/components/layout/headers/BriefingsHeader";
import { BriefingArchive } from "@/features/briefing/components/BriefingArchive";
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
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-4xl px-6 pt-3 pb-12">
        <BriefingArchive />
      </div>
    </div>
  );
}
