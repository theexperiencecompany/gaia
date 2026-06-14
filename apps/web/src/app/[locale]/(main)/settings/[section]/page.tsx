import { redirect } from "next/navigation";
import type { SettingsSection } from "@/features/settings/config/sectionKeys";
import {
  DEFAULT_SECTION,
  isValidSection,
} from "@/features/settings/config/sectionKeys";
import SettingsSectionClient from "./SettingsSectionClient";

interface PageProps {
  params: Promise<{ readonly section: string }>;
}

export default async function SettingsSectionPage({ params }: PageProps) {
  const { section } = await params;

  if (!isValidSection(section)) {
    redirect(`/settings/${DEFAULT_SECTION}`);
  }

  return <SettingsSectionClient section={section as SettingsSection} />;
}
