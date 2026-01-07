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

// =============================================================================
// DISPLAY INFO FUNCTIONS
// =============================================================================

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
 * Get trigger display information using backend schemas and handler registry.
 *
 * @param workflow - The workflow to get display info for
 * @param integrations - List of available integrations
 * @param schemas - Optional trigger schemas from backend (for enhanced display)
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
  const handler = getTriggerHandler(trigger_config.type);

  // Get display info from handler
  let displayInfo: TriggerDisplayInfo;
  if (handler) {
    const schema = schemas?.find((s) => handler.triggerSlugs.includes(s.slug));
    displayInfo = handler.getDisplayInfo(
      trigger_config as TriggerConfig,
      schema,
    );
  } else {
    // Fallback for unknown triggers
    displayInfo = {
      label: "unknown trigger",
      integrationId: null,
    };
  }

  // Special handling for schedule triggers - use cron description
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
 * Uses backend schemas as source of truth.
 *
 * @param integrations - Connected integrations
 * @param schemas - Trigger schemas from backend
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
    .filter((t) => t.integration); // Only show triggers with connected integrations
}
