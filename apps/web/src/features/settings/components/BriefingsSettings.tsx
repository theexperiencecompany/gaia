"use client";

import { NotificationIcon } from "@icons";
import dynamic from "next/dynamic";
import { LinkButton } from "@/components/shared/LinkButton";
import { NOTIFICATION_PLATFORMS } from "@/features/notification/constants";
import { BriefingScheduleSettings } from "@/features/settings/components/BriefingScheduleSettings";
import { ChatChannelSelect } from "@/features/settings/components/ChatChannelSelect";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { NOTIFICATIONS_SETTINGS_PATH } from "@/features/settings/constants";
import { useChatChannelSettings } from "@/features/settings/hooks/useChatChannelSettings";
import { usePlatformLinks } from "@/features/settings/hooks/usePlatformLinks";

// The editions grid carries its own thumbnails; load it after the schedule has painted.
const BriefingEditionsSettings = dynamic(() =>
  import("@/features/settings/components/BriefingEditionsSettings").then(
    (m) => m.BriefingEditionsSettings,
  ),
);

/** Where briefs land: the one chat app they go to, chosen here when several are linked. */
function BriefDeliveryRow() {
  const { isLinked } = usePlatformLinks();
  const { linkedOrder, saving, putFirst } = useChatChannelSettings(
    NOTIFICATION_PLATFORMS.filter(isLinked),
  );
  const choosesApp = linkedOrder !== null && linkedOrder.length > 1;
  return (
    <SettingsRow
      label="Where briefs land"
      description={
        choosesApp
          ? "In GAIA, by email if email is on, and in one chat app: the one you chatted on lately, otherwise this one. Quiet hours hold them."
          : "In GAIA, by email if email is on, and in your linked chat app. Quiet hours hold them."
      }
      icon={
        <div className="flex size-9 items-center justify-center rounded-xl bg-zinc-800">
          <NotificationIcon className="size-4 text-zinc-400" />
        </div>
      }
    >
      {choosesApp ? (
        <ChatChannelSelect
          linkedOrder={linkedOrder}
          saving={saving}
          putFirst={putFirst}
        />
      ) : (
        <LinkButton
          href={NOTIFICATIONS_SETTINGS_PATH}
          size="sm"
          variant="default-soft"
        >
          Notifications
        </LinkButton>
      )}
    </SettingsRow>
  );
}

/** Settings > Briefings: when briefs come, where they land, and which editions they draw. */
export function BriefingsSettings() {
  return (
    <SettingsPage>
      <BriefingScheduleSettings />
      <SettingsSection title="Delivery">
        <BriefDeliveryRow />
      </SettingsSection>
      <BriefingEditionsSettings />
    </SettingsPage>
  );
}
