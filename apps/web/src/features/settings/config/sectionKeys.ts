export const DEFAULT_SECTION = "account";

export const VALID_SECTIONS = [
  "account",
  "profile",
  "linked-accounts",
  "subscription",
  "usage",
  "preferences",
  "instructions",
  "memory",
  "notifications",
  "desktop",
] as const;

export type SettingsSection = (typeof VALID_SECTIONS)[number];

export function isValidSection(section: string): section is SettingsSection {
  return (VALID_SECTIONS as readonly string[]).includes(section);
}
