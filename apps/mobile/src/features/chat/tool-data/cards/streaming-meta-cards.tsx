import { Card } from "heroui-native";
import { useMemo, useState } from "react";
import { Pressable, View } from "react-native";
import {
  Alert01Icon,
  AppIcon,
  ArrowDown01Icon,
  CpuIcon,
  FlowIcon,
  Settings01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

interface ToolCallEntry {
  tool_call_id?: string;
  tool_name?: string;
  tool_category?: string;
  inputs?: Record<string, unknown>;
  message?: string;
  output?: string;
  integration_name?: string;
  show_category?: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const getToolCategoryLabel = (tool: ToolCallEntry): string => {
  if (tool.integration_name) return tool.integration_name;
  const cat = tool.tool_category;
  if (!cat || cat === "unknown") return "";
  return cat
    .replace(/_/g, " ")
    .split(" ")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
};

// ---------------------------------------------------------------------------
// ToolCallsCard
// ---------------------------------------------------------------------------

export function ToolCallsCard({ data }: { data: unknown }) {
  const calls = (Array.isArray(data) ? data : [data]) as ToolCallEntry[];
  const [openCallIds, setOpenCallIds] = useState<Record<string, boolean>>({});

  const uniqueToolsCount = useMemo(() => {
    const set = new Set(
      calls.map((call) => call.tool_category || call.tool_name),
    );
    return set.size;
  }, [calls]);

  const toggle = (id: string) => {
    setOpenCallIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center justify-between mb-3">
          <View className="flex-row items-center gap-2">
            <View className="w-5 h-5 rounded-md bg-white/10 items-center justify-center">
              <AppIcon
                icon={CpuIcon}
                size={12}
                color="#8e8e93"
                strokeWidth={2}
              />
            </View>
            <Text className="text-xs font-medium text-[#8e8e93]">
              Tool execution
            </Text>
          </View>
          <Text className="text-xs text-[#8e8e93]">
            {calls.length} call{calls.length !== 1 ? "s" : ""} ·{" "}
            {uniqueToolsCount} tool{uniqueToolsCount !== 1 ? "s" : ""}
          </Text>
        </View>

        {/* Tool call rows */}
        {calls.map((call, idx) => {
          const label =
            call.message || call.integration_name || call.tool_name || "Tool";
          const categoryLabel = getToolCategoryLabel(call);
          const key =
            call.tool_call_id ||
            call.tool_name ||
            call.integration_name ||
            `${label}-${idx}`;
          const isOpen = !!openCallIds[key];
          const hasInputs = call.inputs && Object.keys(call.inputs).length > 0;
          const hasOutput = !!call.output?.trim();
          const hasDetails = hasInputs || hasOutput;
          const isLast = idx === calls.length - 1;

          return (
            <View key={key} className="flex-row items-stretch gap-3">
              {/* Timeline spine */}
              <View className="items-center" style={{ width: 20 }}>
                <View className="w-5 h-5 rounded-md bg-white/8 items-center justify-center mt-0.5">
                  <AppIcon
                    icon={Settings01Icon}
                    size={11}
                    color="#8e8e93"
                    strokeWidth={2}
                  />
                </View>
                {!isLast && <View className="w-px flex-1 bg-white/10 mt-1" />}
              </View>

              {/* Content */}
              <View className={`flex-1 ${isLast ? "mb-0" : "mb-3"}`}>
                <Pressable
                  onPress={() => hasDetails && toggle(key)}
                  className="flex-row items-center gap-1"
                >
                  <Text className="text-sm font-medium text-foreground flex-1">
                    {label}
                  </Text>
                  {hasDetails && (
                    <AppIcon
                      icon={ArrowDown01Icon}
                      size={14}
                      color="#8e8e93"
                      strokeWidth={2}
                      style={{
                        transform: [{ rotate: isOpen ? "180deg" : "0deg" }],
                      }}
                    />
                  )}
                </Pressable>

                {!!categoryLabel && call.show_category !== false && (
                  <Text className="text-[11px] text-[#8e8e93] mt-0.5">
                    {categoryLabel}
                  </Text>
                )}

                {isOpen && hasDetails && (
                  <View className="mt-2 rounded-xl bg-black/30 p-3 gap-2">
                    {hasInputs && (
                      <View>
                        <Text className="text-[10px] text-[#8e8e93] font-medium mb-1">
                          INPUT
                        </Text>
                        <Text
                          className="text-xs text-foreground font-mono"
                          numberOfLines={8}
                        >
                          {JSON.stringify(call.inputs, null, 2)}
                        </Text>
                      </View>
                    )}
                    {hasOutput && (
                      <View>
                        <Text className="text-[10px] text-[#8e8e93] font-medium mb-1">
                          OUTPUT
                        </Text>
                        <Text
                          className="text-xs text-foreground"
                          numberOfLines={10}
                        >
                          {call.output}
                        </Text>
                      </View>
                    )}
                  </View>
                )}
              </View>
            </View>
          );
        })}
      </Card.Body>
    </Card>
  );
}

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
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center gap-2 mb-3">
          <View className="w-5 h-5 rounded-md bg-primary/15 items-center justify-center">
            <AppIcon icon={CpuIcon} size={12} color="#00bbff" strokeWidth={2} />
          </View>
          <Text className="text-xs font-medium text-[#8e8e93]">
            Interactive app
          </Text>
        </View>

        {/* App info */}
        <View className="flex-row items-start gap-3 mb-3">
          <View className="w-10 h-10 rounded-xl bg-primary/10 items-center justify-center shrink-0">
            <AppIcon
              icon={FlowIcon}
              size={20}
              color="#00bbff"
              strokeWidth={2}
            />
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
                className="text-[11px] text-[#8e8e93] mt-0.5"
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
              color="#8e8e93"
              strokeWidth={2}
              style={{ marginTop: 1 }}
            />
            <Text className="text-xs text-[#8e8e93] flex-1 leading-relaxed">
              Interactive rendering is available on web. The result is still
              included in the conversation.
            </Text>
          </View>
        </View>
      </Card.Body>
    </Card>
  );
}
