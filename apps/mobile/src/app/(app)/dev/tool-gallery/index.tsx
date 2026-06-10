import { TOOL_FIXTURES } from "@gaia/shared/chat";
import { useRouter } from "expo-router";
import { Pressable, ScrollView, View } from "react-native";
import { Text } from "@/components/ui/text";
import { StyledSafeAreaView } from "@/lib/uniwind";

export default function ToolGalleryIndex() {
  const router = useRouter();

  return (
    <StyledSafeAreaView className="flex-1 bg-background">
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ paddingHorizontal: 16, paddingVertical: 24 }}
      >
        <View className="mb-6">
          <Text className="text-2xl font-semibold text-zinc-100">
            Tool Card Gallery
          </Text>
          <Text className="mt-2 text-sm text-zinc-400">
            Select a tool to preview it in isolation. Compare with web at{" "}
            <Text className="font-mono text-xs text-zinc-300">
              /dev/tool-gallery/[toolName]
            </Text>
            .
          </Text>
        </View>

        <View className="gap-2">
          {TOOL_FIXTURES.map((fixture) => (
            <Pressable
              key={fixture.toolName}
              onPress={() =>
                router.push(`/(app)/dev/tool-gallery/${fixture.toolName}`)
              }
              android_ripple={{ color: "rgba(255,255,255,0.05)" }}
              className="rounded-xl bg-zinc-900 px-4 py-3"
            >
              <Text className="text-sm font-medium text-zinc-200">
                {fixture.label}
              </Text>
              <Text className="mt-0.5 font-mono text-[10px] text-zinc-500">
                {fixture.toolName}
              </Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </StyledSafeAreaView>
  );
}
