"use client";

import { Button } from "@heroui/button";
import { NotificationIcon } from "@icons";
import dynamic from "next/dynamic";
import Link from "next/link";
import { BriefingScheduleSettings } from "@/features/settings/components/BriefingScheduleSettings";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";

// The editions grid carries its own thumbnails; load it after the schedule has painted.
const BriefingEditionsSettings = dynamic(() =>
  import("@/features/settings/components/BriefingEditionsSettings").then(
    (m) => m.BriefingEditionsSettings,
  ),
);

const NOTIFICATIONS_SETTINGS_PATH = "/settings/notifications";

/** Settings > Briefings: when briefs come, where they land, and which editions they draw. */
export function BriefingsSettings() {
  return (
    <SettingsPage>
      <BriefingScheduleSettings />
      <SettingsSection title="Delivery">
        <SettingsRow
          label="Where briefs land"
          description="In GAIA, by email while email notifications are on, and in the chat app GAIA texts you on. Quiet hours hold them until they end."
          icon={
            <div className="flex size-9 items-center justify-center rounded-xl bg-zinc-800">
              <NotificationIcon className="size-4 text-zinc-400" />
            </div>
          }
        >
          <Button
            as={Link}
            href={NOTIFICATIONS_SETTINGS_PATH}
            size="sm"
            variant="flat"
          >
            Notifications
          </Button>
        </SettingsRow>
      </SettingsSection>
      <BriefingEditionsSettings />
    </SettingsPage>
  );
}
