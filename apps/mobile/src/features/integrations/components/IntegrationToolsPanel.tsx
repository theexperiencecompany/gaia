import { useMemo } from "react";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { IntegrationTool } from "../types";
import {
  IntegrationToolApprovals,
  type ToolEntry,
} from "./IntegrationToolApprovals";

interface IntegrationToolsPanelProps {
  tools: IntegrationTool[];
  /**
   * Optional category prefix to strip from each tool name before display.
   * Mirrors the web sidebar which removes e.g. "Notion " from
   * "Notion Add Multiple Page Content" so chips read more naturally.
   */
  categoryPrefix?: string;
  /**
   * Connected integrations show the per-tool approval checklist; not-connected
   * ones show a plain browse view of what the integration can do.
   */
  isConnected?: boolean;
}

/**
 * Convert snake/screaming-snake names to Title Case and trim a trailing
 * "Tool" suffix. Matches the web `formatToolName` exactly.
 */
function formatToolName(toolName: string): string {
  return toolName
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/-/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .replace(/\s{1,8}tool$/i, "")
    .trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * A connected integration's tool list is the per-tool approval checklist; a
 * not-connected one shows a plain "Available Tools (N)" flex-wrap of pills.
 */
export function IntegrationToolsPanel({
  tools,
  categoryPrefix,
  isConnected = false,
}: IntegrationToolsPanelProps) {
  const { fontSize, spacing } = useResponsive();

  const entries = useMemo<ToolEntry[]>(() => {
    const prefixRegex = categoryPrefix
      ? new RegExp(`^${escapeRegExp(categoryPrefix)}\\s*`, "i")
      : null;
    return tools.map((tool) => {
      const formatted = formatToolName(tool.name);
      const label = prefixRegex
        ? formatted.replace(prefixRegex, "").trim() || formatted
        : formatted;
      return { name: tool.name, label, destructive: tool.destructive ?? false };
    });
  }, [tools, categoryPrefix]);

  if (entries.length === 0) {
    return null;
  }

  if (isConnected) {
    return <IntegrationToolApprovals entries={entries} />;
  }

  return (
    <View style={{ gap: spacing.sm }}>
      <Text
        className="text-zinc-400"
        style={{ fontSize: fontSize.xs, fontWeight: "500", marginBottom: 2 }}
      >
        Available Tools ({entries.length})
      </Text>

      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {entries.map((tool) => (
          <View
            key={tool.name}
            style={{
              borderRadius: 999,
              paddingHorizontal: 10,
              paddingVertical: 4,
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.12)",
              alignSelf: "flex-start",
            }}
          >
            <Text
              className="text-zinc-300"
              numberOfLines={1}
              style={{ fontSize: fontSize.xs, fontWeight: "300" }}
            >
              {tool.label}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}
