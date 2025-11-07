/**
 * Utility functions for displaying trigger information using integration data
 */

import { TRIGGER_CONFIG } from "@/config/registries/triggerRegistry";
import { Integration } from "@/features/integrations/types";

import { Workflow } from "../api/workflowApi";
import { getScheduleDescription } from "./cronUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

/**
 * Get trigger configuration for a workflow type
 */
const getTriggerConfig = (triggerType: string) => {
  return TRIGGER_CONFIG[triggerType as keyof typeof TRIGGER_CONFIG];
};

/**
 * Find integration by ID
 */
const findIntegration = (
  integrations: Integration[],
  integrationId: string | null,
) => {
  if (!integrationId) return null;
  return (
    integrations.find((integration) => integration.id === integrationId) || null
  );
};

/**
 * MAIN FUNCTION: Get complete trigger display information in single pass
 * This replaces getTriggerIcon, getTriggerLabel, getIntegrationFromTrigger, and getTriggerDisplay
 */
export const getTriggerDisplay = (
  workflow: Workflow,
  integrations: Integration[],
) => {
  const { trigger_config } = workflow;
  const config = getTriggerConfig(trigger_config.type);
  const integration = findIntegration(
    integrations,
    config?.integrationId || null,
  );

  // Generate label with special handling for schedule triggers
  const label =
    trigger_config.type === "schedule" && trigger_config.cron_expression
      ? getScheduleDescription(trigger_config.cron_expression)
      : config?.label || "unknown trigger";

  return {
    icon: getToolCategoryIcon(integration?.category || "default"),
    label,
    integration,
  };
};

/**
 * Get trigger-enabled integrations for WorkflowModal dropdown
 */
export const getTriggerEnabledIntegrations = (integrations: Integration[]) => {
  return Object.entries(TRIGGER_CONFIG)
    .filter(([_, config]) => config.integrationId) // Only trigger types with integrations
    .map(([triggerType, config]) => {
      const integration = findIntegration(integrations, config.integrationId);
      return {
        id: config.integrationId!,
        name: config.name,
        description: config.description,
        icon: getToolCategoryIcon(integration?.category || "default"),
        triggerType,
      };
    })
    .filter((t) => t.icon); // Only show integrations with icons
};
