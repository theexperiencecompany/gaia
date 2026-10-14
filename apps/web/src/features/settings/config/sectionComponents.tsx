"use client";

import type React from "react";
import AccountSettings from "@/features/settings/components/AccountSettings";
import BrowserSettings from "@/features/settings/components/BrowserSettings";
import DesktopSettings from "@/features/settings/components/DesktopSettings";
import DevicesSettings from "@/features/settings/components/DevicesSettings";
import ExperimentalFeaturesSettings from "@/features/settings/components/ExperimentalFeaturesSettings";
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

type SetModalAction = React.Dispatch<React.SetStateAction<ModalAction | null>>;

interface SectionComponentProps {
  readonly section: SettingsSection;
  readonly setModalAction: SetModalAction;
}

// One panel per section; the two that confirm through a modal get its setter.
const SECTION_PANELS: Record<
  SettingsSection,
  (setModalAction: SetModalAction) => React.ReactNode
> = {
  account: (setModalAction) => (
    <AccountSettings setModalAction={setModalAction} />
  ),
  profile: () => <ProfileCardSettings />,
  "linked-accounts": () => <LinkedAccountsSettings />,
  subscription: () => <SubscriptionSettings />,
  usage: () => <UsageSettings />,
  preferences: (setModalAction) => (
    <PreferencesSettings setModalAction={setModalAction} />
  ),
  voice: () => <VoiceSettings />,
  instructions: () => <IntegrationInstructionsSettings />,
  memory: () => <MemorySettings />,
  skills: () => <SkillsSettings />,
  notifications: () => <NotificationSettings />,
  devices: () => <DevicesSettings />,
  browser: () => <BrowserSettings />,
  experimental: () => <ExperimentalFeaturesSettings />,
  desktop: () => <DesktopSettings />,
};

export function SectionComponent({
  section,
  setModalAction,
}: SectionComponentProps) {
  return SECTION_PANELS[section](setModalAction);
}
