/**
 * Trigger Registry - Single Source of Truth for Workflow Trigger Configuration
 *
 * This registry provides centralized configuration for// Helper to get config schema for a trigger type
export const getTriggerConfigSchema = <T extends TriggerType>(
  type: T
): TriggerRegistryConfig[T]["configSchema"] => {
  return TRIGGER_CONFIG[type].configSchema;
};

// Helper to get trigger metadata
export const getTriggerMetadata = <T extends TriggerType>(
  type: T
): Omit<TriggerRegistryConfig[T], "configSchema"> => {
  const { configSchema, ...metadata } = TRIGGER_CONFIG[type];
  return metadata;
};ypes.
 * Add new trigger types here only - everything else auto-derives from this configuration.
 */

/**
 * SINGLE SOURCE OF TRUTH: Trigger configuration mapping
 * Add new trigger types here only - everything else auto-derives from this
 *
 * Field Explanations:
 *
 * @param integrationId - The ID of the integration to use for this trigger type
 *   - When NOT null: Uses the specified integration's icon from the integrations API
 *   - When null: Uses fallback default icons (Clock for schedule, Manual icon for manual)
 *   - Examples: "gmail" → fetches Gmail integration icon, "google_calendar" → fetches Calendar icon
 *
 * @param label - Short display text shown on workflow cards and UI elements
 *   - Used in WorkflowCard chips and trigger display components
 *   - Keep concise (2-4 words): "on new emails", "on calendar events"
 *   - For schedule triggers: can be overridden by cron description if available
 *
 * @param name - Human-readable integration name for dropdowns and forms
 *   - Used in WorkflowModal trigger selection dropdown
 *   - Should match the integration's display name: "Gmail", "Google Calendar"
 *   - For non-integration triggers: descriptive name like "Schedule", "Manual"
 *
 * @param description - Detailed explanation for user-facing tooltips and help text
 *   - Used in WorkflowModal dropdown descriptions
 *   - Explains when/how the trigger activates: "Trigger when new emails arrive"
 *   - Should be clear and actionable for end users
 *
 * @param configSchema - Type-safe schema for trigger-specific configuration fields
 *   - Defines what fields are available for each trigger type
 *   - Used for form generation, validation, and TypeScript type generation
 *   - Each field specifies type, optionality, and description
 *
 * Icon Sources:
 * - Integration triggers (integrationId !== null): Icons from integrations API via integration.icons[0]
 * - Non-integration triggers (integrationId === null): Fallback to default Lucide icons
 *   - Schedule: Clock icon from Lucide
 *   - Manual: CursorMagicSelection icon from custom icons
 */
export const TRIGGER_CONFIG = {
  email: {
    integrationId: "gmail",
    label: "on new emails",
    name: "Gmail",
    description: "Trigger when new emails arrive",
    configSchema: {},
  },
  // calendar: {
  //   integrationId: "google_calendar",
  //   label: "on calendar events",
  //   name: "Google Calendar",
  //   description: "Trigger when new events are created",
  //   configSchema: {
  //     // Future: calendar-specific config fields
  //   },
  // },
  schedule: {
    integrationId: null, // No integration needed
    label: "scheduled", // Will be overridden by cron description if available
    name: "Schedule",
    description: "Trigger on a schedule",
    configSchema: {
      cron_expression: {
        type: "string",
        optional: false,
        description: "Cron expression defining the schedule",
      },
      timezone: {
        type: "string",
        optional: false,
        description: "Timezone for schedule execution",
      },
      next_run: {
        type: "string",
        optional: true,
        description: "Next scheduled execution time",
      },
    },
  },
  manual: {
    integrationId: null,
    label: "manual trigger",
    name: "Manual",
    description: "Trigger manually",
    configSchema: {
      // Manual triggers have no additional configuration
    },
  },
} as const;

// Auto-generated types from the registry
export type TriggerType = keyof typeof TRIGGER_CONFIG;
export type TriggerRegistryConfig = typeof TRIGGER_CONFIG;

// Base trigger configuration
interface BaseTriggerConfig {
  type: TriggerType;
  enabled: boolean;
}

// Specific trigger configurations (discriminated union)
export interface EmailTriggerConfig extends BaseTriggerConfig {
  type: "email";
  // No filtering fields - triggers on every email
}

export interface CalendarTriggerConfig extends BaseTriggerConfig {
  type: "calendar";
  // Future: calendar-specific fields
}

export interface ScheduleTriggerConfig extends BaseTriggerConfig {
  type: "schedule";
  cron_expression: string;
  timezone: string;
  next_run?: string;
}

export interface ManualTriggerConfig extends BaseTriggerConfig {
  type: "manual";
  // Manual triggers have no additional configuration
}

// Union type for type-safe trigger configurations
export type TriggerConfig =
  | EmailTriggerConfig
  | CalendarTriggerConfig
  | ScheduleTriggerConfig
  | ManualTriggerConfig;

// Helper to get trigger types at runtime
export const TRIGGER_TYPES = Object.keys(TRIGGER_CONFIG) as TriggerType[];

// Type guard for runtime validation
export const isTriggerType = (type: string): type is TriggerType => {
  return type in TRIGGER_CONFIG;
};

// Helper to get config schema for a trigger type
export const getTriggerConfigSchema = <T extends TriggerType>(
  type: T,
): TriggerRegistryConfig[T]["configSchema"] => {
  return TRIGGER_CONFIG[type].configSchema;
};

// Helper to get trigger metadata
export const getTriggerMetadata = <T extends TriggerType>(
  type: T,
): Omit<TriggerRegistryConfig[T], "configSchema"> => {
  const { ...metadata } = TRIGGER_CONFIG[type];
  return metadata;
};
