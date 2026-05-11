/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type { ToolInfo } from "@/features/chat/api/toolsApi";

import type { EnhancedToolInfo } from "@/features/chat/types/enhancedTools";

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

const EMPTY_TOOLS: ToolInfo[] = Object.freeze([]) as ToolInfo[];

const NO_MATCH = Object.freeze({
  isSlashCommand: false,
  query: "",
  matches: [] as SlashCommandMatch[],
  commandStart: -1,
  commandEnd: -1,
});

export const useSlashCommands = (): UseSlashCommandsReturn => ({
  tools: EMPTY_TOOLS,
  isLoadingTools: false,
  error: null,
  detectSlashCommand: () => NO_MATCH,
  getSlashCommandSuggestions: () => [],
  getAllTools: () => EMPTY_TOOLS,
});
