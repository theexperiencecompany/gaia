"use client";

import { BriefingArchive } from "@/features/briefing/components/BriefingArchive";

export default function BriefingsPage() {
  return (
    <div className="mx-auto h-fit min-h-screen w-full max-w-4xl overflow-y-scroll px-6 py-8">
      <h1 className="mb-6 text-xl font-medium text-zinc-100">Briefings</h1>
      <BriefingArchive />
    </div>
  );
}
