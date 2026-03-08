import { useRouter } from "expo-router";
import { Button, Card } from "heroui-native";
import { Pressable, ScrollView, View } from "react-native";
import {
  ArrowLeft01Icon,
  HugeiconsIcon,
  SparklesIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

const QUICK_PROMPTS = [
  "Create a workflow that triages incoming emails",
  "Build a daily calendar digest workflow",
  "Create a social listening workflow for my brand",
];

export default function WorkflowsPage() {
  const router = useRouter();

  return (
    <View className="flex-1 bg-[#0b0c0f]">
      <View className="px-4 pt-14 pb-4 border-b border-white/10">
        <View className="flex-row items-center justify-between">
          <Pressable
            onPress={() => router.back()}
            className="h-9 w-9 rounded-full items-center justify-center bg-white/5"
          >
            <HugeiconsIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
          </Pressable>
          <Text className="text-base font-semibold">Workflows</Text>
          <View className="h-9 w-9" />
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, gap: 10 }}>
        <Card className="rounded-xl bg-[#17191f]">
          <Card.Body className="p-4">
            <View className="flex-row items-center gap-2 mb-2">
              <HugeiconsIcon icon={SparklesIcon} size={16} color="#b3b9ff" />
              <Text className="text-sm font-semibold">
                Workflow Studio (Mobile)
              </Text>
            </View>
            <Text className="text-sm text-muted">
              Full workflow editing is still web-first. You can preview
              suggested workflows in chat and open web to edit advanced steps.
            </Text>
          </Card.Body>
        </Card>

        <Text className="text-xs text-muted mt-1">Quick prompts</Text>
        {QUICK_PROMPTS.map((prompt) => (
          <Card key={prompt} className="rounded-xl bg-[#13151a]">
            <Card.Body className="px-4 py-3">
              <Text className="text-sm">{prompt}</Text>
            </Card.Body>
          </Card>
        ))}

        <Button
          variant="primary"
          className="mt-2"
          onPress={() => router.replace("/(app)/index")}
        >
          <Button.Label>Ask GAIA to build a workflow</Button.Label>
        </Button>
      </ScrollView>
    </View>
  );
}
