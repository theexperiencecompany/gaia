"use client";

import { Skeleton } from "@heroui/skeleton";
import { ExperimentalFeatureRow } from "@/features/settings/components/ExperimentalFeatureRow";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useFeatureFlags } from "@/features/settings/hooks/useFeatureFlags";

export default function ExperimentalFeaturesSettings() {
  const { features, isLoading, isEmpty } = useFeatureFlags();

  return (
    <SettingsPage>
      <div>
        <h2 className="text-lg font-medium text-white">
          Experimental features
        </h2>
        <p className="mt-1 text-sm leading-relaxed text-zinc-400">
          Try what GAIA is still building. These can change, break on some
          tasks, or go away, and you can switch them off at any time.
        </p>
      </div>

      <SettingsSection>
        {isLoading && (
          <div className="flex items-center gap-4 px-4 py-3.5">
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3.5 w-40 rounded-lg" />
              <Skeleton className="h-3 w-72 rounded-lg" />
            </div>
            <Skeleton className="h-5 w-9 rounded-full" />
          </div>
        )}
        {isEmpty && (
          <SettingsRow
            label="Nothing to try right now"
            description="New experiments will show up here."
          />
        )}
        {features.map((feature) => (
          <ExperimentalFeatureRow key={feature.key} feature={feature} />
        ))}
      </SettingsSection>
    </SettingsPage>
  );
}
