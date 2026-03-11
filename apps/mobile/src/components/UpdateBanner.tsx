import { Pressable, View } from "react-native";
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
        backgroundColor: "#00bbff",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: 16,
        paddingVertical: 10,
      }}
    >
      <Text style={{ color: "#000", fontWeight: "500", fontSize: 13, flex: 1 }}>
        An update is available
      </Text>
      <View style={{ flexDirection: "row", gap: 8 }}>
        <Pressable
          onPress={applyUpdate}
          accessibilityRole="button"
          accessibilityLabel="Update now"
          style={{
            backgroundColor: "#000",
            borderRadius: 8,
            paddingHorizontal: 12,
            paddingVertical: 5,
          }}
        >
          <Text style={{ color: "#00bbff", fontWeight: "600", fontSize: 12 }}>
            Update Now
          </Text>
        </Pressable>
        <Pressable
          onPress={dismissUpdate}
          accessibilityRole="button"
          accessibilityLabel="Dismiss update"
          style={{
            paddingHorizontal: 8,
            paddingVertical: 5,
          }}
        >
          <Text style={{ color: "#000", fontSize: 12 }}>Later</Text>
        </Pressable>
      </View>
    </View>
  );
}
