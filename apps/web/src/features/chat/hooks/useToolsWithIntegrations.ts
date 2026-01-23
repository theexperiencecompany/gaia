import { useMemo } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

import type { ToolInfo } from "../api/toolsApi";
import type { EnhancedToolInfo } from "../types/enhancedTools";
import { useToolsQuery } from "./useToolsQuery";

export interface UseToolsWithIntegrationsReturn {
  tools: EnhancedToolInfo[];
  toolsByCategory: Record<string, EnhancedToolInfo[]>;
  isLoading: boolean;
  error: Error | null;
  categories: string[];
  getToolsForCategory: (category: string) => EnhancedToolInfo[];
  isToolLocked: (toolName: string) => boolean;
  getLockedToolsCount: () => number;
  getUnlockedToolsCount: () => number;
}

/**
 * Hook that combines tool information with integration status
 * to determine which tools are locked/available
 */
export const useToolsWithIntegrations = (): UseToolsWithIntegrationsReturn => {
  const { integrations } = useIntegrations();

  // Use shared tools query with consistent 3-hour caching
  const {
    tools: toolsArray,
    isLoading: toolsLoading,
    error: toolsError,
  } = useToolsQuery();

  // Convert tools array to the expected format with categories
  const toolsData = useMemo(() => {
    if (!toolsArray.length) return null;

    // Extract unique categories from tools
    const categories = Array.from(
      new Set(toolsArray.map((tool) => tool.category)),
    );

    return {
      tools: toolsArray,
      categories,
      total_count: toolsArray.length,
    };
  }, [toolsArray]);

  // Combine tools with integration status
  const enhancedTools = useMemo((): EnhancedToolInfo[] => {
    if (!toolsData?.tools) return [];

    return toolsData.tools.map((tool: ToolInfo): EnhancedToolInfo => {
      // Check if integration is connected (use category as integration ID)
      const integration = integrations.find(
        (int) => int.id.toLowerCase() === tool.category.toLowerCase(),
      );
      const isLocked = !integration || integration.status !== "connected";

      // Simple, direct property access - no fallbacks needed
      return {
        name: tool.name,
        category: tool.category,
        displayName: tool.display_name, // Single source of truth from backend
        iconUrl: tool.icon_url,
        isLocked,
      };
    });
  }, [toolsData?.tools, integrations]);

  // Group tools by category
  const toolsByCategory = useMemo((): Record<string, EnhancedToolInfo[]> => {
    const categorized: Record<string, EnhancedToolInfo[]> = {};

    enhancedTools.forEach((tool) => {
      if (!categorized[tool.category]) {
        categorized[tool.category] = [];
      }
      categorized[tool.category].push(tool);
    });

    // Sort tools within each category (unlocked first, then by name)
    Object.keys(categorized).forEach((category) => {
      categorized[category].sort((a, b) => {
        // Unlocked tools first
        if (a.isLocked !== b.isLocked) {
          return a.isLocked ? 1 : -1;
        }
        // Then alphabetically
        return a.name.localeCompare(b.name);
      });
    });

    return categorized;
  }, [enhancedTools]);

  // Extract categories
  const categories = useMemo((): string[] => {
    return toolsData?.categories || [];
  }, [toolsData?.categories]);

  // Helper functions
  const getToolsForCategory = (category: string): EnhancedToolInfo[] => {
    return toolsByCategory[category] || [];
  };

  const isToolLocked = (toolName: string): boolean => {
    const tool = enhancedTools.find((t) => t.name === toolName);
    return tool?.isLocked || false;
  };

  const getLockedToolsCount = (): number => {
    return enhancedTools.filter((tool) => tool.isLocked).length;
  };

  const getUnlockedToolsCount = (): number => {
    return enhancedTools.filter((tool) => !tool.isLocked).length;
  };

  return {
    tools: enhancedTools,
    toolsByCategory,
    isLoading: toolsLoading,
    error: toolsError ? new Error(toolsError) : null,
    categories,
    getToolsForCategory,
    isToolLocked,
    getLockedToolsCount,
    getUnlockedToolsCount,
  };
};
