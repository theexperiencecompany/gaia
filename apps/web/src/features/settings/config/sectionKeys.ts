export const DEFAULT_SECTION = "account";

export const VALID_SECTIONS = [
  "account",
  "profile",
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
  "briefings",
  "postmarks",
  "devices",
  "browser",
  "experimental",
  "desktop",
] as const;

export type SettingsSection = (typeof VALID_SECTIONS)[number];

/** Sections folded into another; their old links land on the one that owns them now. */
export const MOVED_SECTIONS: Readonly<Record<string, SettingsSection>> = {
  "linked-accounts": "notifications",
};

export function isValidSection(section: string): section is SettingsSection {
  return (VALID_SECTIONS as readonly string[]).includes(section);
}
