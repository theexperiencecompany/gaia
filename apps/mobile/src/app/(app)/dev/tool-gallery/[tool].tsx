import { TOOL_FIXTURES } from "@gaia/shared/chat";
import { useLocalSearchParams } from "expo-router";
import { useMemo } from "react";
import { ScrollView, View } from "react-native";
import { Text } from "@/components/ui/text";
import type { ToolDataEntry } from "@/features/chat/tool-data/registry";
import { ToolDataRenderer } from "@/features/chat/tool-data/renderers";
import { StyledSafeAreaView } from "@/lib/uniwind";
import { BackButton } from "@/shared/components/ui/back-button";

function normalizeParam(raw: string | string[] | undefined): string | null {
  if (!raw) return null;
  const value = Array.isArray(raw) ? raw[0] : raw;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export default function ToolGalleryToolPage() {
  const { tool } = useLocalSearchParams<{ tool?: string | string[] }>();
  const toolName = normalizeParam(tool);

  const fixture = useMemo(
    () => TOOL_FIXTURES.find((f) => f.toolName === toolName) ?? null,
    [toolName],
  );

  const toolData = useMemo<ToolDataEntry[]>(
    () =>
      fixture
        ? [
            {
              tool_name: fixture.toolName,
              data: fixture.data as Record<string, unknown>,
              timestamp: new Date().toISOString(),
            },
          ]
        : [],
    [fixture],
  );

  return (
    <StyledSafeAreaView className="flex-1 bg-background">
      <View className="flex-row items-center gap-3 px-4 py-3">
        <BackButton />
        <View className="flex-1">
          <Text className="text-base font-semibold text-zinc-100">
            {fixture?.label ?? "Unknown tool"}
          </Text>
          <Text className="mt-0.5 font-mono text-[10px] text-zinc-500">
            {toolName ?? ""}
          </Text>
        </View>
      </View>

      {fixture?.description ? (
        <View className="px-4 pb-3">
          <Text className="text-xs text-zinc-500">{fixture.description}</Text>
        </View>
      ) : null}

      <ScrollView
        className="flex-1"
        contentContainerStyle={{ paddingVertical: 8, paddingBottom: 32 }}
      >
        {fixture ? (
          <ToolDataRenderer toolData={toolData} />
        ) : (
          <View className="px-4 py-8">
            <Text className="text-sm text-zinc-500">
              Unknown tool:{" "}
              <Text className="font-mono text-zinc-400">{toolName ?? ""}</Text>
            </Text>
          </View>
        )}
      </ScrollView>
    </StyledSafeAreaView>
  );
}
