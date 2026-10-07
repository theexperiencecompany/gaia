import { MAX_INSTRUCTIONS_CHARS } from "@gaia/shared/constants/instructions";
import { Button, Card, Spinner, TextField } from "heroui-native";
import { Alert, View } from "react-native";
import { Text } from "@/components/ui/text";
import { SectionHeader } from "@/features/settings/components/section-header";
import { useGlobalInstructions } from "@/features/settings/hooks/use-global-instructions";
import { useResponsive } from "@/lib/responsive";

export function GlobalInstructionsCard() {
  const { fontSize } = useResponsive();
  const instructions = useGlobalInstructions();

  const handleLoadLatest = async () => {
    try {
      await instructions.loadLatest();
    } catch {
      Alert.alert("Error", "Failed to load the latest instructions.");
    }
  };

  const handleSave = async (baseRevision?: number) => {
    try {
      const result = await instructions.save(baseRevision);
      if (result.status === "saved") {
        Alert.alert("Saved", "Custom instructions updated.");
        return;
      }
      Alert.alert(
        "Instructions changed elsewhere",
        "GAIA or another device saved new instructions after you opened this screen. Your text is still here.",
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Load latest",
            onPress: () => {
              void handleLoadLatest();
            },
          },
          {
            text: "Keep mine",
            onPress: () => {
              void handleSave(result.currentRevision);
            },
          },
        ],
      );
    } catch {
      Alert.alert("Error", "Failed to save custom instructions.");
    }
  };

  return (
    <Card variant="secondary" className="rounded-2xl bg-surface">
      <Card.Body className="gap-3 px-4 py-4">
        <SectionHeader>Custom Instructions</SectionHeader>
        {instructions.isLoading ? (
          <Spinner />
        ) : !instructions.isLoaded ? (
          <View className="gap-3">
            <Text className="text-zinc-500" style={{ fontSize: fontSize.sm }}>
              Couldn't load your custom instructions.
            </Text>
            <Button
              variant="secondary"
              onPress={() => {
                void instructions.retryLoad();
              }}
            >
              <Button.Label>Retry</Button.Label>
            </Button>
          </View>
        ) : (
          <>
            <TextField>
              <TextField.Input
                value={instructions.value}
                onChangeText={instructions.setValue}
                placeholder="Tell GAIA how you'd like it to respond..."
                maxLength={MAX_INSTRUCTIONS_CHARS}
                editable={!instructions.isSaving}
                multiline
                numberOfLines={4}
                style={{ minHeight: 100 }}
              />
            </TextField>
            <Text
              className="self-end text-zinc-500"
              style={{ fontSize: fontSize.xs }}
            >
              {`${instructions.value.length} / ${MAX_INSTRUCTIONS_CHARS}`}
            </Text>
            <Button
              onPress={() => {
                void handleSave();
              }}
              isDisabled={!instructions.isDirty || instructions.isSaving}
              className="bg-primary"
            >
              {instructions.isSaving ? (
                <Spinner />
              ) : (
                <Button.Label>Save Instructions</Button.Label>
              )}
            </Button>
          </>
        )}
      </Card.Body>
    </Card>
  );
}
