"use client";

import MemoryManagement from "@/features/memory/components/MemoryManagement";

export default function MemorySettings() {
  return (
    <div className="h-full w-full space-y-6">
      {/* <SettingsCard
        icon={<AiBrain01Icon className="h-5 w-5" />}
        title="Memory Management"
        className="flex h-full flex-col"
      >
        <p className="mb-6 text-sm text-foreground-400">
          Manage the information GAIA remembers from your conversations
        </p>
        <MemoryManagement />
        </SettingsCard>
        */}
      <MemoryManagement />
    </div>
  );
}
