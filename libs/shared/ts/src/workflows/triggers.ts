/**
 * Framework-agnostic trigger helpers shared between web and mobile.
 *
 * Web's full handler registry pulls in HeroUI/React; for mobile (and any
 * other consumer that just needs to render a list of triggers grouped by
 * integration, look up logos, and format labels) these pure helpers are
 * sufficient.
 *
 * The schema shape mirrors `apps/web/src/features/workflows/triggers/types/base.ts`
 * exactly — backend is the single source of truth.
 */

// ---------------------------------------------------------------------------
// Schema types (mirror backend payload)
// ---------------------------------------------------------------------------

export interface TriggerFieldSchema {
  type: "string" | "integer" | "boolean" | "number";
  default: unknown;
  min?: number;
  max?: number;
  options_endpoint?: string;
  description?: string;
}

export interface TriggerSchema {
  slug: string;
  composio_slug: string;
  name: string;
  description: string;
  provider: string;
  integration_id: string;
  config_schema: Record<string, TriggerFieldSchema>;
}

// ---------------------------------------------------------------------------
// Built-in (non-integration) triggers
// ---------------------------------------------------------------------------

export interface BuiltinTriggerMeta {
  id: "manual" | "schedule";
  label: string;
  description: string;
}

export const BUILTIN_TRIGGER_META: BuiltinTriggerMeta[] = [
  {
    id: "manual",
    label: "Manual",
    description: "Run on demand from chat or app",
  },
  {
    id: "schedule",
    label: "Scheduled",
    description: "Run on a time-based schedule",
  },
];

// ---------------------------------------------------------------------------
// Integration grouping
// ---------------------------------------------------------------------------

export interface IntegrationTriggerGroup {
  integrationId: string;
  schemas: TriggerSchema[];
}

/**
 * Group trigger schemas by `integration_id`. Returns groups in stable
 * alphabetical order so list rendering is deterministic.
 *
 * This mirrors the grouping web does in `TriggerAutocomplete` — the source of
 * truth is which schemas the backend exposes, not a hardcoded integration list.
 */
export function groupTriggerSchemasByIntegration(
  schemas: TriggerSchema[],
): IntegrationTriggerGroup[] {
  const buckets = new Map<string, TriggerSchema[]>();
  for (const schema of schemas) {
    const key = schema.integration_id || "other";
    const existing = buckets.get(key);
    if (existing) {
      existing.push(schema);
    } else {
      buckets.set(key, [schema]);
    }
  }
  return Array.from(buckets.entries())
    .map(([integrationId, list]) => ({
      integrationId,
      schemas: list.slice().sort((a, b) => a.name.localeCompare(b.name)),
    }))
    .sort((a, b) => a.integrationId.localeCompare(b.integrationId));
}

// ---------------------------------------------------------------------------
// Logo key resolution
// ---------------------------------------------------------------------------

/**
 * Backend trigger schemas use snake_case integration ids
 * (`google_calendar`, `google_sheets`, `google_docs`, `microsoft_teams`,
 * `google_maps`).
 * The shared logo registry uses short keys (`googlecalendar`,
 * `googlesheets`, `googledocs`).
 *
 * This is the authoritative mapping used wherever an `integration_id`
 * needs to be resolved to a logo key. Add new entries here when the
 * backend introduces a new schema id whose canonical key differs from
 * the integration_id.
 */
const TRIGGER_INTEGRATION_TO_LOGO_KEY: Record<string, string> = {
  google_calendar: "googlecalendar",
  googlecalendar: "googlecalendar",
  google_sheets: "googlesheets",
  googlesheets: "googlesheets",
  google_docs: "googledocs",
  googledocs: "googledocs",
  google_tasks: "googletasks",
  googletasks: "googletasks",
  google_meet: "googlemeet",
  googlemeet: "googlemeet",
};

/**
 * Resolve the logo registry key for a trigger schema's `integration_id`.
 * Returns the input verbatim when no remap is required (the registry's
 * default convention is `lowercase, no underscores`).
 */
export function getTriggerLogoKey(integrationId: string): string {
  if (!integrationId) return integrationId;
  const remap = TRIGGER_INTEGRATION_TO_LOGO_KEY[integrationId];
  if (remap) return remap;
  // Fallback: strip underscores so `microsoft_teams` -> `microsoft_teams`
  // (which is itself a registry key) and `google_xyz` -> `googlexyz`
  // attempts the unprefixed lookup as a last resort.
  return integrationId;
}

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

/**
 * Convert a snake_case integration id into a Title-Cased display label.
 * Keeps two-letter caps (e.g. `github` stays as "Github" — callers that
 * want exact branding should map specific ids upstream).
 */
export function formatIntegrationLabel(integrationId: string): string {
  if (!integrationId) return "";
  return integrationId
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Lookup helpers used by both web's autocomplete and mobile's stepwise picker.
 */
export function findTriggerSchema(
  schemas: TriggerSchema[] | undefined,
  slugOrComposioSlug: string,
): TriggerSchema | undefined {
  if (!schemas || !slugOrComposioSlug) return undefined;
  return schemas.find(
    (s) =>
      s.slug === slugOrComposioSlug || s.composio_slug === slugOrComposioSlug,
  );
}

export function getSchemaFieldEntries(
  schema: TriggerSchema,
): Array<{ name: string; schema: TriggerFieldSchema }> {
  return Object.entries(schema.config_schema).map(([name, fieldSchema]) => ({
    name,
    schema: fieldSchema,
  }));
}

export function buildDefaultTriggerConfig(slug: string): {
  type: string;
  enabled: boolean;
} {
  return { type: slug, enabled: true };
}
