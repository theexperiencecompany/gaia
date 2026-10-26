import type { IntegrationCombo } from "@/features/integrations/data/combosData";

/** Tool slugs the combo data spells two ways, folded onto the one app page they share. */
const TOOL_SLUG_ALIASES: Record<string, string> = {
  teams: "microsoft-teams",
};

/** Each app's site, whose favicon stands in where the icon catalog has no logo for it. */
const APP_DOMAINS: Record<string, string> = {
  airtable: "airtable.com",
  asana: "asana.com",
  clickup: "clickup.com",
  discord: "discord.com",
  figma: "figma.com",
  github: "github.com",
  gmail: "gmail.com",
  "google-calendar": "calendar.google.com",
  "google-docs": "docs.google.com",
  "google-drive": "drive.google.com",
  "google-sheets": "sheets.google.com",
  hubspot: "hubspot.com",
  jira: "atlassian.com",
  linear: "linear.app",
  loom: "loom.com",
  "microsoft-teams": "teams.microsoft.com",
  notion: "notion.so",
  salesforce: "salesforce.com",
  slack: "slack.com",
  stripe: "stripe.com",
  todoist: "todoist.com",
  trello: "trello.com",
  zoom: "zoom.us",
};

export interface ComboApp {
  readonly slug: string;
  readonly name: string;
}

/** An app with every combo it is part of, in slug order. */
export interface ComboAppGroup extends ComboApp {
  readonly combos: readonly IntegrationCombo[];
}

function appSlugOf(toolSlug: string): string {
  return TOOL_SLUG_ALIASES[toolSlug] ?? toolSlug;
}

/** The favicon URL for an app the icon catalog may not carry. */
export function appIconUrl(appSlug: string): string | undefined {
  const domain = APP_DOMAINS[appSlug];
  return domain
    ? `https://www.google.com/s2/favicons?domain=${domain}&sz=128`
    : undefined;
}

/** A combo's two apps, in the order the combo names them. */
export function comboAppsOf(
  combo: IntegrationCombo,
): readonly [ComboApp, ComboApp] {
  return [
    { slug: appSlugOf(combo.toolASlug), name: combo.toolA },
    { slug: appSlugOf(combo.toolBSlug), name: combo.toolB },
  ];
}

/** /automate/with/<app>: every combo of one app. */
export function appPagePath(appSlug: string): string {
  return `/automate/with/${appSlug}`;
}

/** Every app with its combos, the apps with the most combos first. */
export function comboAppGroups(
  combos: readonly IntegrationCombo[],
): ComboAppGroup[] {
  const byApp = new Map<string, { name: string; combos: IntegrationCombo[] }>();
  for (const combo of combos) {
    for (const app of comboAppsOf(combo)) {
      const group = byApp.get(app.slug) ?? { name: app.name, combos: [] };
      group.combos.push(combo);
      byApp.set(app.slug, group);
    }
  }
  return [...byApp]
    .map(([slug, group]) => ({
      slug,
      name: group.name,
      combos: [...group.combos].sort((a, b) => a.slug.localeCompare(b.slug)),
    }))
    .sort(
      (a, b) =>
        b.combos.length - a.combos.length || a.name.localeCompare(b.name),
    );
}
