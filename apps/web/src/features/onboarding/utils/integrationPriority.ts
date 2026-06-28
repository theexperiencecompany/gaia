/**
 * Builds the order integrations are surfaced in during the `integrationSelect`
 * stage: a general most-popular set first, then a set tailored to the user's
 * profession archetype (builder / operator / founder / scholar / default).
 *
 * Values are integration *display names* (lowercased); they are matched against
 * the live catalog, so any name not present simply has no effect. Reuses the
 * profession→archetype bucketing from the platform-preview step so the two
 * stay in sync.
 */

import {
  getArchetype,
  type ProfessionArchetype,
} from "../constants/platformPreviewMessages";

/**
 * Recognizable apps everyone sees first (≈ the opening row), regardless of
 * profession.
 */
const GENERAL_POPULAR_NAMES = [
  "gmail",
  "google calendar",
  "google docs",
  "google meet",
  "google sheets",
];

/** Profession-tailored apps surfaced right after the general set. */
const ARCHETYPE_INTEGRATION_NAMES: Record<ProfessionArchetype, string[]> = {
  builder: [
    "github",
    "slack",
    "linear",
    "microsoft teams",
    "jira",
    "gitlab",
    "figma",
    "notion",
  ],
  operator: [
    "slack",
    "hubspot",
    "salesforce",
    "airtable",
    "asana",
    "trello",
    "microsoft teams",
    "notion",
  ],
  founder: [
    "slack",
    "notion",
    "stripe",
    "hubspot",
    "airtable",
    "linear",
    "calendly",
  ],
  scholar: [
    "notion",
    "zotero",
    "onedrive",
    "dropbox",
    "slack",
    "microsoft teams",
    "evernote",
  ],
  default: ["slack", "notion", "trello", "dropbox", "zoom", "whatsapp"],
};

/**
 * Ordered, de-duplicated list of integration names to surface first in the
 * onboarding picker for a given profession.
 */
export function getOnboardingIntegrationPriority(
  profession: string | undefined,
): string[] {
  const archetype = getArchetype(profession);
  return [
    ...new Set([
      ...GENERAL_POPULAR_NAMES,
      ...ARCHETYPE_INTEGRATION_NAMES[archetype],
    ]),
  ];
}
