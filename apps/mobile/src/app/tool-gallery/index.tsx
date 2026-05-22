import { TOOL_FIXTURES } from "@gaia/shared/chat";
import { Stack, useRouter } from "expo-router";
import { ScrollView, TouchableOpacity, View } from "react-native";
import { Text } from "@/components/ui/text";
import { StyledSafeAreaView } from "@/lib/uniwind";

export default function ToolGalleryIndexScreen() {
  const router = useRouter();

  return (
    <StyledSafeAreaView className="flex-1 bg-background">
      <Stack.Screen options={{ title: "Tool Gallery", headerShown: true }} />
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ paddingBottom: 32 }}
      >
        <View className="px-4 py-4">
          <Text className="text-zinc-100 text-2xl font-semibold">
            Tool Card Gallery
          </Text>
          <Text className="text-zinc-500 text-xs mt-1.5">
            Tap a tool to preview it in isolation.
          </Text>
        </View>

        <View className="px-4 gap-2">
          {TOOL_FIXTURES.map((fixture) => (
            <TouchableOpacity
              key={fixture.toolName}
              onPress={() =>
                router.push(
                  `/tool-gallery/${fixture.toolName}` as Parameters<
                    typeof router.push
                  >[0],
                )
              }
              activeOpacity={0.7}
            >
              <View className="rounded-xl bg-zinc-900 px-4 py-3">
                <Text className="text-zinc-200 text-sm font-medium">
                  {fixture.label}
                </Text>
                <Text className="text-zinc-500 font-mono text-[10px] mt-0.5">
                  {fixture.toolName}
                </Text>
              </View>
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>
    </StyledSafeAreaView>
  );
}
