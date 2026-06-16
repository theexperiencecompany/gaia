"use client";

import type React from "react";
import { ReferralsSettings } from "@/features/referrals";
import AccountSettings from "@/features/settings/components/AccountSettings";
import { IntegrationInstructionsSettings } from "@/features/settings/components/IntegrationInstructionsSettings";
import LinkedAccountsSettings from "@/features/settings/components/LinkedAccountsSettings";
import MemorySettings from "@/features/settings/components/MemorySettings";
import NotificationSettings from "@/features/settings/components/NotificationSettings";
import PreferencesSettings from "@/features/settings/components/PreferencesSettings";
import ProfileCardSettings from "@/features/settings/components/ProfileCardSettings";
import type { ModalAction } from "@/features/settings/components/SettingsMenu";
import { SubscriptionSettings } from "@/features/settings/components/SubscriptionSettings";
import UsageSettings from "@/features/settings/components/UsageSettings";
import type { SettingsSection } from "./sectionKeys";

interface SectionComponentProps {
  readonly section: SettingsSection;
  readonly setModalAction: React.Dispatch<
    React.SetStateAction<ModalAction | null>
  >;
}

export function SectionComponent({
  section,
  setModalAction,
}: SectionComponentProps) {
  switch (section) {
    case "account":
      return <AccountSettings setModalAction={setModalAction} />;
    case "profile":
      return <ProfileCardSettings />;
    case "linked-accounts":
      return <LinkedAccountsSettings />;
    case "subscription":
      return <SubscriptionSettings />;
    case "referrals":
      return <ReferralsSettings />;
    case "usage":
      return <UsageSettings />;
    case "preferences":
      return <PreferencesSettings setModalAction={setModalAction} />;
    case "instructions":
      return <IntegrationInstructionsSettings />;
    case "memory":
      return <MemorySettings />;
    case "notifications":
      return <NotificationSettings />;
  }
}
