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
    <div className="mx-auto h-fit min-h-screen w-full max-w-4xl overflow-y-scroll px-6 py-8">
      <BriefingArchive />
    </div>
  );
}
