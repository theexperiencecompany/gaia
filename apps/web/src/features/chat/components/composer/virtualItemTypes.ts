import type { SlashCommandMatch } from "@/features/chat/hooks/useSlashCommands";

/** Types for the slash command dropdown's virtualized items */
export type VirtualItemType =
  | { type: "integrations-card" }
  | { type: "unlocked-tool"; match: SlashCommandMatch; toolIndex: number }
  | {
      type: "locked-category-header";
      category: string;
      tools: SlashCommandMatch[];
      requiredIntegration: { id: string; name: string };
    }
  | { type: "locked-tool"; match: SlashCommandMatch };
