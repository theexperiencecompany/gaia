import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { IntegrationTool } from "../types";

interface IntegrationToolsPanelProps {
  tools: IntegrationTool[];
  /**
   * Optional category prefix to strip from each tool name before display.
   * Mirrors the web sidebar which removes e.g. "Notion " from
   * "Notion Add Multiple Page Content" so chips read more naturally.
   */
  categoryPrefix?: string;
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

/**
 * Web-parity tools list: a plain "Available Tools (N)" subheading followed
 * by a flex-wrap of bordered pill chips, one per tool. No card wrapper, no
 * descriptions, no collapse — every tool is shown at once just like the
 * web `IntegrationSidebar`.
 */
export function IntegrationToolsPanel({
  tools,
  categoryPrefix,
}: IntegrationToolsPanelProps) {
  const { fontSize, spacing } = useResponsive();

  if (tools.length === 0) {
    return null;
  }

  const prefixRegex = categoryPrefix
    ? new RegExp(`^${categoryPrefix}\\s*`, "i")
    : null;

  return (
    <View style={{ gap: spacing.sm }}>
      <Text
        className="text-zinc-400"
        style={{
          fontSize: fontSize.xs,
          fontWeight: "500",
          marginBottom: 2,
        }}
      >
        Available Tools ({tools.length})
      </Text>

      <View
        style={{
          flexDirection: "row",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        {tools.map((tool) => {
          const formatted = formatToolName(tool.name);
          const label = prefixRegex
            ? formatted.replace(prefixRegex, "").trim()
            : formatted;
          return (
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
                {label || formatted}
              </Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}
