import { redirect } from "next/navigation";
import { EffectSettingsAccountBranch } from "@/components/effect/EffectSettingsAccountBranch";
import type { SettingsSection } from "@/features/settings/config/sectionKeys";
import {
  DEFAULT_SECTION,
  isValidSection,
} from "@/features/settings/config/sectionKeys";
import { EFFECT_UI_ENABLED } from "@/config/effectUi";
import SettingsSectionClient from "./SettingsSectionClient";

interface PageProps {
  params: Promise<{ readonly section: string }>;
  searchParams: Promise<{ readonly effect?: string }>;
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1/";

export default async function SettingsSectionPage({
  params,
  searchParams,
}: PageProps) {
  const { section } = await params;
  const { effect } = await searchParams;

  if (!isValidSection(section)) {
    redirect(`/settings/${DEFAULT_SECTION}`);
  }

  // The Account section is ported to Effect UI; `?effect=1` swaps it in.
  if (effect === "1" && section === "account" && EFFECT_UI_ENABLED) {
    return <EffectSettingsAccountBranch apiBaseUrl={API_BASE_URL} />;
  }

  return <SettingsSectionClient section={section as SettingsSection} />;
}
