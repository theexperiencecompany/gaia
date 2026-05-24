import { OPENUI_SAMPLES, type OpenUISample } from "@gaia/shared/utils";
import { Stack } from "expo-router";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import { OpenUIRenderer } from "@/features/chat/components/openui/OpenUIRenderer";
import { BackButton } from "@/shared/components/ui/back-button";

function SampleBlock({ sample }: { sample: OpenUISample }) {
  return (
    <View style={{ gap: 10 }}>
      <Text className="text-xs font-semibold uppercase tracking-widest text-zinc-400">
        {sample.name}
      </Text>
      <OpenUIRenderer code={sample.code} isStreaming={false} />
    </View>
  );
}

export default function OpenUIDemoScreen() {
  const insets = useSafeAreaInsets();

  const groups = OPENUI_SAMPLES.reduce<Record<string, OpenUISample[]>>(
    (acc, s) => {
      const bucket = acc[s.group] ?? [];
      bucket.push(s);
      acc[s.group] = bucket;
      return acc;
    },
    {},
  );

  return (
    <View className="flex-1 bg-background">
      <Stack.Screen options={{ headerShown: false }} />

      <View
        style={{
          paddingTop: insets.top + 8,
          paddingBottom: 12,
          paddingHorizontal: 16,
          flexDirection: "row",
          alignItems: "center",
          gap: 12,
        }}
      >
        <BackButton />
        <View style={{ flex: 1 }}>
          <Text className="text-lg font-semibold text-zinc-100">
            OpenUI Gallery
          </Text>
          <Text className="text-xs text-zinc-500">
            All 35 components from shared samples
          </Text>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={{
          paddingHorizontal: 16,
          paddingBottom: insets.bottom + 48,
          gap: 32,
        }}
      >
        {Object.entries(groups).map(([group, samples]) => (
          <View key={group} style={{ gap: 20 }}>
            <Text className="text-base font-semibold text-zinc-200">
              {group}
            </Text>
            <View style={{ gap: 28 }}>
              {samples.map((s) => (
                <SampleBlock key={s.name} sample={s} />
              ))}
            </View>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}
