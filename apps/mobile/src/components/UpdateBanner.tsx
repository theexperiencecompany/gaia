import { Button, PressableFeedback } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { useAppUpdate } from "@/hooks/use-app-update";

export function UpdateBanner() {
  const { isUpdateAvailable, applyUpdate, dismissUpdate } = useAppUpdate();

  if (!isUpdateAvailable) return null;

  return (
    <View
      accessibilityLiveRegion="polite"
      accessibilityLabel="App update available"
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        backgroundColor: "#0ea5e9",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: 16,
        paddingVertical: 10,
      }}
    >
      <Text
        style={{ flex: 1, fontSize: 13, fontWeight: "500", color: "#ffffff" }}
      >
        An update is available
      </Text>
      <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
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
          style={{ paddingHorizontal: 8, paddingVertical: 4 }}
        >
          <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.8)" }}>
            Later
          </Text>
        </PressableFeedback>
      </View>
    </View>
  );
}
