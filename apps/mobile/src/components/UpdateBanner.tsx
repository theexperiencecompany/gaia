import { Alert, Button, PressableFeedback } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { useAppUpdate } from "@/hooks/use-app-update";

export function UpdateBanner() {
  const { isUpdateAvailable, applyUpdate, dismissUpdate } = useAppUpdate();

  if (!isUpdateAvailable) return null;

  return (
    <Alert
      variant="info"
      accessibilityLiveRegion="polite"
      accessibilityLabel="App update available"
      className="absolute top-0 left-0 right-0 z-[9999] rounded-none px-4 py-2.5 flex-row items-center justify-between"
    >
      <Alert.Title className="flex-1 text-[13px] font-medium">
        An update is available
      </Alert.Title>
      <View className="flex-row gap-2 items-center">
        <Button
          size="sm"
          variant="primary"
          onPress={applyUpdate}
          accessibilityRole="button"
          accessibilityLabel="Update now"
        >
          <Button.Label>Update Now</Button.Label>
        </Button>
        <PressableFeedback
          onPress={dismissUpdate}
          accessibilityRole="button"
          accessibilityLabel="Dismiss update"
          className="px-2 py-1"
        >
          <Text className="text-xs">Later</Text>
        </PressableFeedback>
      </View>
    </Alert>
  );
}
