import { TOOL_FIXTURES } from "@gaia/shared/chat";
import { Stack, useLocalSearchParams } from "expo-router";
import { ScrollView, View } from "react-native";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Text } from "@/components/ui/text";
import { TOOL_RENDERERS } from "@/features/chat/tool-data/renderers";
import { StyledSafeAreaView } from "@/lib/uniwind";

function FallbackCard({ label }: { label: string }) {
  return (
    <View className="mx-4 my-1 rounded-2xl bg-zinc-900 p-3">
      <Text className="text-zinc-500 text-sm">
        No mobile renderer for{" "}
        <Text className="text-zinc-400 font-mono">{label}</Text>
      </Text>
    </View>
  );
}

export default function ToolDetailScreen() {
  const { tool } = useLocalSearchParams<{ tool: string }>();
  const fixture = TOOL_FIXTURES.find((f) => f.toolName === tool);

  if (!fixture) {
    return (
      <StyledSafeAreaView className="flex-1 bg-background">
        <Stack.Screen options={{ title: "Unknown Tool", headerShown: true }} />
        <View className="flex-1 items-center justify-center p-8">
          <Text className="text-zinc-500 text-sm">
            Unknown tool:{" "}
            <Text className="text-zinc-400 font-mono">{tool}</Text>
          </Text>
        </View>
      </StyledSafeAreaView>
    );
  }

  const renderer = TOOL_RENDERERS[fixture.toolName];

  return (
    <StyledSafeAreaView className="flex-1 bg-background">
      <Stack.Screen options={{ title: fixture.label, headerShown: true }} />
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ paddingBottom: 48 }}
      >
        <View className="px-4 pb-3 pt-4">
          <Text className="text-zinc-400 text-[11px] font-semibold uppercase tracking-wider">
            {fixture.label}
          </Text>
          <Text className="text-zinc-500 text-xs mt-0.5">
            <Text className="text-zinc-500 font-mono text-xs">
              {fixture.toolName}
            </Text>
            {"  ·  "}
            {fixture.description}
          </Text>
        </View>
        <ErrorBoundary>
          {renderer ? (
            renderer(fixture.data, `gallery-${fixture.toolName}`)
          ) : (
            <FallbackCard label={fixture.toolName} />
          )}
        </ErrorBoundary>
      </ScrollView>
    </StyledSafeAreaView>
  );
}
