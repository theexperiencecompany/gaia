import { DEFAULT_SETTINGS_SECTION } from "../../../../settings-redirects.mjs";

export const DEFAULT_SECTION = DEFAULT_SETTINGS_SECTION;

export const VALID_SECTIONS = [
  "account",
  "profile",
  "linked-accounts",
  "providers",
  "integrations-setup",
  "members",
  "subscription",
  "usage",
  "preferences",
  "voice",
  "instructions",
  "memory",
  "skills",
  "notifications",
  "devices",
  "browser",
  "experimental",
  "desktop",
] as const;

export type SettingsSection = (typeof VALID_SECTIONS)[number];

export function isValidSection(section: string): section is SettingsSection {
  return (VALID_SECTIONS as readonly string[]).includes(section);
}
