/**
 * Utility functions for workflow operations
 */

import type { WorkflowStepType } from "@/types/features/workflowTypes";
import type { ToolInfo } from "@/types/shared/contentTypes";

/**
 * Extract unique categories from workflow steps
 * @param steps - Array of workflow steps
 * @returns Array of unique tools with their categories
 */
export function extractToolsFromSteps(
  steps: Array<{ category: string }>,
): ToolInfo[] {
  if (!steps || steps.length === 0) return [];

  // Use a Map to track unique categories
  const toolsMap = new Map<string, ToolInfo>();

  steps.forEach((step) => {
    if (step.category && !toolsMap.has(step.category)) {
      toolsMap.set(step.category, {
        name: step.category,
        description: "",
        category: step.category,
      });
    }
  });

  return Array.from(toolsMap.values());
}

/**
 * Extract categories from workflow steps
 * @param steps - Array of workflow steps
 * @returns Array of unique categories
 */
export function extractCategoriesFromSteps(
  steps: WorkflowStepType[],
): string[] {
  if (!steps || steps.length === 0) return [];

  const categoriesSet = new Set<string>();

  steps.forEach((step) => {
    if (step.category) {
      categoriesSet.add(step.category);
    }
  });

  return Array.from(categoriesSet);
}
