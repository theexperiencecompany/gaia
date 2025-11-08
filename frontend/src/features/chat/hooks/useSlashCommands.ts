import Fuse from "fuse.js";
import { useCallback, useMemo } from "react";

import { ToolInfo } from "@/features/chat/api/toolsApi";

import { EnhancedToolInfo } from "../types/enhancedTools";
import { useToolsQuery } from "./useToolsQuery";
import { useToolsWithIntegrations } from "./useToolsWithIntegrations";

export interface SlashCommandMatch {
  tool: ToolInfo;
  enhancedTool?: EnhancedToolInfo;
  matchedText: string;
}

export interface UseSlashCommandsReturn {
  tools: ToolInfo[];
  isLoadingTools: boolean;
  error: string | null;
  detectSlashCommand: (
    text: string,
    cursorPosition: number,
  ) => {
    isSlashCommand: boolean;
    query: string;
    matches: SlashCommandMatch[];
    commandStart: number;
    commandEnd: number;
  };
  getSlashCommandSuggestions: (query: string) => SlashCommandMatch[];
  getAllTools: () => ToolInfo[];
}

export const useSlashCommands = (): UseSlashCommandsReturn => {
  // Use React Query hook for fetching tools with caching
  const { tools, isLoading: isLoadingTools, error } = useToolsQuery();

  // Get enhanced tools with integration status
  const { tools: enhancedTools } = useToolsWithIntegrations();

  // Create Fuse instance with optimized config for fuzzy search
  const fuse = useMemo(() => {
    const toolsWithEnhanced = tools.map((tool) => {
      const enhancedTool = enhancedTools.find((et) => et.name === tool.name);
      return {
        tool,
        enhancedTool,
        // Create searchable strings
        nameSpaced: tool.name.replace(/_/g, " "),
        category: tool.category,
      };
    });

    return new Fuse(toolsWithEnhanced, {
      keys: [
        {
          name: "nameSpaced",
          weight: 4, // Highest priority for spaced name matches
        },
        {
          name: "tool.name",
          weight: 2,
        },
        {
          name: "category",
          weight: 1, // Lower priority for category matches
        },
      ],
      threshold: 0.35, // Lower = more strict, higher = more fuzzy (0-1)
      distance: 100, // Maximum distance for fuzzy matching
      includeScore: true,
      minMatchCharLength: 1,
      ignoreLocation: true, // Match anywhere in string
      useExtendedSearch: false,
      shouldSort: true,
      findAllMatches: true, // Find all pattern matches
    });
  }, [tools, enhancedTools]);

  const getSlashCommandSuggestions = useCallback(
    (query: string): SlashCommandMatch[] => {
      // If no query, show all tools sorted by unlock status, category and name
      if (!query.trim()) {
        return tools
          .map((tool) => {
            const enhancedTool = enhancedTools.find(
              (et) => et.name === tool.name,
            );
            return {
              tool,
              enhancedTool,
              matchedText: tool.name,
            };
          })
          .sort((a, b) => {
            // Unlocked tools first
            const aLocked = a.enhancedTool?.isLocked || false;
            const bLocked = b.enhancedTool?.isLocked || false;
            if (aLocked !== bLocked) {
              return aLocked ? 1 : -1;
            }

            // Then sort by category, then by name
            if (a.tool.category !== b.tool.category) {
              return a.tool.category.localeCompare(b.tool.category);
            }
            return a.tool.name.localeCompare(b.tool.name);
          });
      }

      // Use Fuse.js for fuzzy search
      const results = fuse.search(query.trim());

      // Convert Fuse results to SlashCommandMatch[]
      return results.map((result) => ({
        tool: result.item.tool,
        enhancedTool: result.item.enhancedTool,
        matchedText: result.item.tool.name,
      }));
    },
    [tools, enhancedTools, fuse],
  );

  const detectSlashCommand = useCallback(
    (text: string, cursorPosition: number) => {
      // Find the last slash before the cursor position
      const textBeforeCursor = text.substring(0, cursorPosition);
      const lastSlashIndex = textBeforeCursor.lastIndexOf("/");

      // Check if this is a potential slash command
      if (lastSlashIndex === -1) {
        return {
          isSlashCommand: false,
          query: "",
          matches: [],
          commandStart: -1,
          commandEnd: -1,
        };
      }

      // Check if the slash is at the beginning of the text or preceded by whitespace
      const charBeforeSlash =
        lastSlashIndex > 0 ? text[lastSlashIndex - 1] : " ";
      const isValidSlashPosition =
        lastSlashIndex === 0 || /\s/.test(charBeforeSlash);

      if (!isValidSlashPosition) {
        return {
          isSlashCommand: false,
          query: "",
          matches: [],
          commandStart: -1,
          commandEnd: -1,
        };
      }

      // Check if there's a space immediately after the slash
      const textAfterSlash = text.substring(lastSlashIndex + 1);
      if (textAfterSlash.startsWith(" ")) {
        return {
          isSlashCommand: false,
          query: "",
          matches: [],
          commandStart: -1,
          commandEnd: -1,
        };
      }

      // Find the end of the potential command - extend to next slash or end of text to allow spaces after words
      const nextSlashIndex = textAfterSlash.indexOf("/");
      const commandEnd =
        nextSlashIndex === -1
          ? text.length
          : lastSlashIndex + 1 + nextSlashIndex;

      // Only consider it a slash command if cursor is within the command
      if (cursorPosition > commandEnd) {
        return {
          isSlashCommand: false,
          query: "",
          matches: [],
          commandStart: -1,
          commandEnd: -1,
        };
      }

      const query = text.substring(lastSlashIndex + 1, cursorPosition);
      const matches = getSlashCommandSuggestions(query);

      return {
        isSlashCommand: true,
        query,
        matches,
        commandStart: lastSlashIndex,
        commandEnd,
      };
    },
    [getSlashCommandSuggestions],
  );

  const getAllTools = useCallback(() => {
    return tools;
  }, [tools]);

  return {
    tools,
    isLoadingTools,
    error: error || null,
    detectSlashCommand,
    getSlashCommandSuggestions,
    getAllTools,
  };
};
