"use client";

import { GridSection } from "@/features/chat/components/interface";

export default function HomePage() {
  return (
    <div className="flex flex-col p-4 min-h-screen h-fit overflow-y-scroll">
      <div className="flex flex-col p-3 mb-10">
        <h1 className="font-semibold text-4xl">Welcome, Aryan</h1>
      </div>
      <GridSection />
    </div>
  );
}
