/**
 * Trigger Display Utilities
 *
 * Helper functions for displaying trigger information using backend schemas.
 */

import type { Integration } from "@/features/integrations/types";

import type { Workflow } from "../api/workflowApi";
import { getScheduleDescription } from "../utils/cronUtils";
import { getTriggerHandler, type TriggerDisplayInfo } from "./registry";
import type { TriggerConfig, TriggerSchema } from "./types";

/**
 * Find integration by ID from list.
 */
const findIntegration = (
  integrations: Integration[],
  integrationId: string | null,
): Integration | null => {
  if (!integrationId) return null;
  return (
    integrations.find((integration) => integration.id === integrationId) || null
  );
};

/**
 * Find a trigger schema by slug or composio_slug.
 * Backend may return composio_slug (e.g., "GITHUB_PULL_REQUEST_EVENT")
 * but frontend uses slug (e.g., "github_pr_event").
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

/**
 * Normalize a trigger identifier to the frontend slug.
 * Converts composio_slug to slug if needed.
 */
export function normalizeTriggerSlug(
  schemas: TriggerSchema[] | undefined,
  slugOrComposioSlug: string,
): string {
  const schema = findTriggerSchema(schemas, slugOrComposioSlug);
  return schema?.slug ?? slugOrComposioSlug;
}

/**
 * Get trigger display information using backend schemas and handler registry.
 */
export function getTriggerDisplayInfo(
  workflow: Workflow,
  integrations: Integration[],
  schemas?: TriggerSchema[],
): {
  integrationId: string | undefined;
  label: string;
  integration: Integration | null;
} {
  const { trigger_config } = workflow;

  const triggerSlug = (trigger_config.trigger_name ||
    trigger_config.trigger_slug ||
    trigger_config.type) as string;

  const handler = getTriggerHandler(triggerSlug);

  let displayInfo: TriggerDisplayInfo;
  if (handler) {
    const schema = schemas?.find((s) => handler.triggerSlugs.includes(s.slug));
    displayInfo = handler.getDisplayInfo(
      trigger_config as TriggerConfig,
      schema,
    );
  } else {
    displayInfo = {
      label: "unknown trigger",
      integrationId: null,
    };
  }

  if (
    trigger_config.type === "schedule" &&
    "cron_expression" in trigger_config
  ) {
    const cronExpression = trigger_config.cron_expression;
    if (typeof cronExpression === "string") {
      const cronDesc = getScheduleDescription(cronExpression);
      if (cronDesc) {
        displayInfo.label = cronDesc;
      }
    }
  }

  const integration = findIntegration(integrations, displayInfo.integrationId);

  return {
    integrationId: integration?.id,
    label: displayInfo.label,
    integration,
  };
}

/**
 * Get trigger-enabled integrations for WorkflowModal dropdown.
 */
export function getTriggerEnabledIntegrations(
  integrations: Integration[],
  schemas: TriggerSchema[],
) {
  return schemas
    .map((schema) => {
      const integration = findIntegration(integrations, schema.integration_id);
      return {
        id: schema.slug,
        integrationId: schema.integration_id,
        name: schema.name,
        description: schema.description,
        integration,
        triggerType: schema.slug,
      };
    })
    .filter((t) => t.integration);
}
