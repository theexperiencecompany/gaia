import { View } from "react-native";
import { Alert01Icon, AppIcon, CpuIcon, FlowIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// ---------------------------------------------------------------------------
// MCPAppCard
// ---------------------------------------------------------------------------

export function MCPAppCard({ data }: { data: unknown }) {
  const app = data as Record<string, unknown>;
  const toolName =
    typeof app.tool_name === "string" ? app.tool_name : "Interactive app";
  const serverUrl = typeof app.server_url === "string" ? app.server_url : null;

  const displayName = toolName
    .split("_")
    .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

  return (
    <ToolCardShell>
      <ToolCardHeader icon={CpuIcon} title="Interactive app" />

      {/* App info */}
      <View className="flex-row items-start gap-3 mb-3">
        <View className="w-10 h-10 rounded-xl bg-primary/10 items-center justify-center shrink-0">
          <AppIcon icon={FlowIcon} size={20} color="#00bbff" strokeWidth={2} />
        </View>
        <View className="flex-1 min-w-0">
          <Text
            className="text-sm font-medium text-foreground"
            numberOfLines={1}
          >
            {displayName}
          </Text>
          {!!serverUrl && (
            <Text
              className="text-[11px] text-zinc-400 mt-0.5"
              numberOfLines={1}
            >
              {serverUrl.replace(/^https?:\/\//, "")}
            </Text>
          )}
        </View>
      </View>

      {/* Notice */}
      <View className="rounded-xl bg-white/5 border border-white/8 px-3 py-2.5">
        <View className="flex-row items-start gap-2">
          <AppIcon
            icon={Alert01Icon}
            size={14}
            color="#a1a1aa"
            strokeWidth={2}
            style={{ marginTop: 1 }}
          />
          <Text className="text-xs text-zinc-400 flex-1 leading-relaxed">
            Interactive rendering is available on web. The result is still
            included in the conversation.
          </Text>
        </View>
      </View>
    </ToolCardShell>
  );
}
