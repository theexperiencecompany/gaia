/**
 * Utility functions for workflow operations
 */

import type { WorkflowStepType } from "@/types/features/workflowTypes";
import type { ToolInfo } from "@/types/shared/contentTypes";

/**
 * Extract unique tools from workflow steps
 * @param steps - Array of workflow steps
 * @returns Array of unique tools with their categories
 */
export function extractToolsFromSteps(
  steps: Array<{ tool_name: string; tool_category: string }>,
): ToolInfo[] {
  if (!steps || steps.length === 0) return [];

  // Use a Map to track unique tools by name
  const toolsMap = new Map<string, ToolInfo>();

  steps.forEach((step) => {
    if (step.tool_name && step.tool_category && !toolsMap.has(step.tool_name)) {
      toolsMap.set(step.tool_name, {
        name: step.tool_name,
        description: "", // Not available in workflow steps
        category: step.tool_category,
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
    if (step.tool_category) {
      categoriesSet.add(step.tool_category);
    }
  });

  return Array.from(categoriesSet);
}
