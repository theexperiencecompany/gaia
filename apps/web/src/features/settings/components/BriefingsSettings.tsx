"use client";

import { NotificationIcon } from "@icons";
import dynamic from "next/dynamic";
import { LinkButton } from "@/components/shared/LinkButton";
import { BriefingScheduleSettings } from "@/features/settings/components/BriefingScheduleSettings";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { NOTIFICATIONS_SETTINGS_PATH } from "@/features/settings/constants";

// The editions grid carries its own thumbnails; load it after the schedule has painted.
const BriefingEditionsSettings = dynamic(() =>
  import("@/features/settings/components/BriefingEditionsSettings").then(
    (m) => m.BriefingEditionsSettings,
  ),
);

/** Settings > Briefings: when briefs come, where they land, and which editions they draw. */
export function BriefingsSettings() {
  return (
    <SettingsPage>
      <BriefingScheduleSettings />
      <SettingsSection title="Delivery">
        <SettingsRow
          label="Where briefs land"
          description="In GAIA, by email if email is on, and in the chat app GAIA texts you on. Quiet hours hold them."
          icon={
            <div className="flex size-9 items-center justify-center rounded-xl bg-zinc-800">
              <NotificationIcon className="size-4 text-zinc-400" />
            </div>
          }
        >
          <LinkButton
            href={NOTIFICATIONS_SETTINGS_PATH}
            size="sm"
            variant="default-soft"
          >
            Notifications
          </LinkButton>
        </SettingsRow>
      </SettingsSection>
      <BriefingEditionsSettings />
    </SettingsPage>
  );
}
