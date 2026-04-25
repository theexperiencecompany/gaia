import { PressableFeedback } from "heroui-native";
import { TextInput, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  PencilEdit02Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface SidebarHeaderProps {
  onNewChat: () => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

export function SidebarHeader({
  onNewChat,
  searchQuery,
  onSearchChange,
}: SidebarHeaderProps) {
  const { spacing, fontSize, iconSize, moderateScale } = useResponsive();

  return (
    <View>
      {/* Top bar: title + new chat */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingHorizontal: spacing.md,
          paddingTop: spacing.md,
          paddingBottom: spacing.sm,
        }}
      >
        <Text
          style={{
            fontSize: fontSize.lg,
            fontWeight: "700",
            color: "#ffffff",
            letterSpacing: -0.3,
          }}
        >
          GAIA
        </Text>
        <PressableFeedback
          onPress={onNewChat}
          hitSlop={8}
          style={{
            padding: 8,
            borderRadius: 8,
            backgroundColor: "rgba(255,255,255,0.06)",
          }}
        >
          <AppIcon icon={PencilEdit02Icon} size={iconSize.sm} color="#a1a1aa" />
        </PressableFeedback>
      </View>

      {/* Search input */}
      <View
        style={{
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.sm,
        }}
      >
        <View style={{ position: "relative" }}>
          <TextInput
            placeholder="Search conversations..."
            placeholderTextColor="#52525b"
            value={searchQuery}
            onChangeText={onSearchChange}
            style={{
              fontSize: fontSize.sm,
              color: "#ffffff",
              backgroundColor: "#1c1c1e",
              borderRadius: moderateScale(10, 0.5),
              paddingHorizontal: moderateScale(12, 0.5),
              paddingVertical: spacing.sm,
              paddingLeft: moderateScale(36, 0.5),
            }}
          />
          <View
            style={{
              position: "absolute",
              left: moderateScale(11, 0.5),
              top: 0,
              bottom: 0,
              justifyContent: "center",
            }}
            pointerEvents="none"
          >
            <AppIcon
              icon={Search01Icon}
              size={iconSize.sm - 1}
              color="#52525b"
            />
          </View>
          {searchQuery.length > 0 && (
            <PressableFeedback
              onPress={() => onSearchChange("")}
              style={{
                position: "absolute",
                right: moderateScale(8, 0.5),
                top: 0,
                bottom: 0,
                justifyContent: "center",
                paddingHorizontal: 4,
              }}
            >
              <AppIcon
                icon={Cancel01Icon}
                size={iconSize.sm - 2}
                color="#52525b"
              />
            </PressableFeedback>
          )}
        </View>
      </View>
    </View>
  );
}
