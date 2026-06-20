"use client";

import type React from "react";
import AccountSettings from "@/features/settings/components/AccountSettings";
import DesktopSettings from "@/features/settings/components/DesktopSettings";
import { IntegrationInstructionsSettings } from "@/features/settings/components/IntegrationInstructionsSettings";
import LinkedAccountsSettings from "@/features/settings/components/LinkedAccountsSettings";
import MemorySettings from "@/features/settings/components/MemorySettings";
import NotificationSettings from "@/features/settings/components/NotificationSettings";
import PreferencesSettings from "@/features/settings/components/PreferencesSettings";
import ProfileCardSettings from "@/features/settings/components/ProfileCardSettings";
import type { ModalAction } from "@/features/settings/components/SettingsMenu";
import SkillsSettings from "@/features/settings/components/SkillsSettings";
import { SubscriptionSettings } from "@/features/settings/components/SubscriptionSettings";
import UsageSettings from "@/features/settings/components/UsageSettings";
import VoiceSettings from "@/features/settings/components/VoiceSettings";
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
    case "usage":
      return <UsageSettings />;
    case "preferences":
      return <PreferencesSettings setModalAction={setModalAction} />;
    case "voice":
      return <VoiceSettings />;
    case "instructions":
      return <IntegrationInstructionsSettings />;
    case "memory":
      return <MemorySettings />;
    case "skills":
      return <SkillsSettings />;
    case "notifications":
      return <NotificationSettings />;
    case "desktop":
      return <DesktopSettings />;
  }
}
